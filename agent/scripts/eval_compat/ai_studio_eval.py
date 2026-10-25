"""Compatibility shim for agents-cli 1.11 / aiplatform 2.6 local evaluation.

Cloud dataset clients become lazy, so in-memory datasets need no ADC. Custom
LLMMetric templates execute through google-genai with the exact original prompt.
The original CLI still handles inference, SDK scoring, JSON and HTML reports.
"""

import functools
import json
import os
import threading
import time
from contextvars import ContextVar
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

_gate = threading.Lock()
_last_call = 0.0
_client = None
_quality_instance = ContextVar("quality_instance", default=None)
_joint_binary = None
_joint_results = {}
_quality_done = {}


class Verdict(BaseModel):
    score: float
    explanation: str


class QualityVerdict(BaseModel):
    score: int = Field(ge=1, le=5)
    explanation: str


class BinaryVerdict(BaseModel):
    score: Literal[0, 1]
    explanation: str


class JointVerdict(BaseModel):
    quality: QualityVerdict
    refusal_or_action: BinaryVerdict


def case_key(instance):
    return json.dumps({key: instance.get(key) for key in (
        "eval_case_id", "prompt", "response", "agent_data", "reference",
    )}, sort_keys=True, ensure_ascii=False, default=str)


def render(template, instance):
    for field, value in instance.items():
        template = template.replace("{" + field + "}", json.dumps(value, ensure_ascii=False, default=str))
    return template


def joint_generate(original_generate, args, kwargs):
    """Batch two original rubrics; project the real verdict back to its caller."""
    instance = _quality_instance.get()
    metric = _joint_binary
    model = kwargs.get("model")
    if instance is None or metric is None or model != (metric.judge_model or os.getenv("AGENT_MODEL", "gemini-3.8-flash")):
        return original_generate(*args, **kwargs)
    config = judge_config(kwargs.get("config"))
    schema = config.response_schema
    if schema is not None and not hasattr(schema, "model_validate"):
        return original_generate(*args, **kwargs)
    prompt = (
        "Evaluate the following two rubrics independently for the same case. "
        "Preserve every original criterion. Return the quality verdict (1-5) "
        "and refusal_or_action verdict (0/1), each with its own explanation.\n\n"
        "ORIGINAL QUALITY EVALUATION:\n" + str(kwargs["contents"])
        + "\n\nORIGINAL REFUSAL_OR_ACTION EVALUATION:\n" + render(metric.prompt_template, instance)
    )
    joint_config = config.model_copy(update={
        "response_schema": None, "response_json_schema": JointVerdict.model_json_schema(),
        "response_mime_type": "application/json",
    })
    request = {**kwargs, "contents": prompt, "config": joint_config}
    response = original_generate(*args, **request)
    verdict = JointVerdict.model_validate_json(response.text)
    quality = verdict.quality.model_dump()
    _joint_results[case_key(instance)] = verdict.refusal_or_action.model_dump()
    parsed = schema.model_validate(quality) if schema is not None else None
    print(f"[judge] joint verdict: quality={verdict.quality.score}, refusal_or_action={verdict.refusal_or_action.score}", flush=True)
    return response.model_copy(update={
        "parsed": parsed,
        "candidates": [types.Candidate(content=types.Content(role="model", parts=[
            types.Part.from_text(text=json.dumps(quality, ensure_ascii=False)),
        ]))],
    })


def judge_config(config):
    """Keep rubric settings and use LOW thinking only when none was specified."""
    if isinstance(config, dict):
        config = types.GenerateContentConfig(**config)
    config = config.model_copy() if config is not None else types.GenerateContentConfig()
    if config.thinking_config is None:
        config.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    return config


def serialized(function, name):
    @functools.wraps(function)
    def evaluate(instance):
        global _last_call
        with _gate:
            time.sleep(max(0, 30 - (time.monotonic() - _last_call)))
            print(f"[judge] {name}: {instance.get('eval_case_id', 'case')}", flush=True)
            token = _quality_instance.set(instance) if name == "custom_response_quality" else None
            try:
                result = function(instance)
                print(f"[judge] {name}: score={result['score']}", flush=True)
                return result
            finally:
                if token is not None:
                    _quality_instance.reset(token)
                    _quality_done.setdefault(case_key(instance), threading.Event()).set()
                _last_call = time.monotonic()
    return evaluate


def template_judge(metric):
    """Keep rubric text, model, sampling count and instruction from the config."""
    template = metric.prompt_template
    model = metric.judge_model or os.getenv("AGENT_MODEL", "gemini-3.8-flash")
    samples = metric.judge_model_sampling_count or 1

    def evaluate(instance):
        global _client
        if _client is None:
            _client = genai.Client()
        prompt = render(template, instance)
        config = dict(metric.judge_model_generation_config or {})
        config.setdefault("temperature", 0)
        config.setdefault("thinking_config", {"thinking_level": "LOW"})
        config.update(response_mime_type="application/json", response_json_schema=Verdict.model_json_schema())
        if metric.judge_model_system_instruction:
            config["system_instruction"] = metric.judge_model_system_instruction
        verdicts = []
        for _ in range(samples):
            response = _client.models.generate_content(model=model, contents=prompt, config=config)
            verdict = Verdict.model_validate_json(response.text)
            if metric.name == "refusal_or_action" and verdict.score not in (0, 1):
                raise ValueError("refusal_or_action judge must return 0 or 1")
            verdicts.append(verdict)
        return {"score": sum(v.score for v in verdicts) / samples,
                "explanation": "\n".join(v.explanation for v in verdicts)}
    return evaluate


def lazy_cloud_client(cls, attribute, factory):
    """Authenticate normally if a cloud URI is actually used; never fake auth."""
    def initialize(self, api_client):
        self.api_client = api_client
        self._ezstore_cloud_client = None

    def get_client(self):
        if self._ezstore_cloud_client is None:
            self._ezstore_cloud_client = factory(
                project=self.api_client.project, credentials=self.api_client._credentials,
            )
        return self._ezstore_cloud_client

    cls.__init__ = initialize
    setattr(cls, attribute, property(get_client))


def install():
    from agentplatform._genai import _bigquery_utils, _gcs_utils
    from google.agents.cli.eval import eval_utils

    lazy_cloud_client(_gcs_utils.GcsUtils, "storage_client", _gcs_utils.storage.Client)
    lazy_cloud_client(_bigquery_utils.BigQueryUtils, "bigquery_client", _bigquery_utils.bigquery.Client)

    # Bound judge requests, including the unchanged independent response_quality
    # function, without touching its prompt or the Agent's model/client process.
    original_client = genai.Client

    def client(*args, **kwargs):
        kwargs.setdefault("http_options", types.HttpOptions(
            timeout=120000,
            retry_options=types.HttpRetryOptions(
                attempts=3, initial_delay=30, max_delay=120, exp_base=2,
                http_status_codes=[429, 503, 504],
            ),
        ))
        result = original_client(*args, **kwargs)
        original_generate = result.models.generate_content

        def generate(*args, **kwargs):
            kwargs["config"] = judge_config(kwargs.get("config"))
            return joint_generate(original_generate, args, kwargs)

        result.models.generate_content = generate
        return result

    genai.Client = client
    original_prepare = eval_utils.prepare_eval_metrics

    @functools.wraps(original_prepare)
    def prepare(*args, **kwargs):
        global _joint_binary
        metrics, local, remote = original_prepare(*args, **kwargs)
        has_quality = any(getattr(metric, "name", None) == "custom_response_quality"
                          and getattr(metric, "custom_function", None) for metric in metrics)
        _joint_binary = next((metric for metric in metrics if
            getattr(metric, "name", None) == "refusal_or_action"
            and getattr(metric, "prompt_template", None)
            and (metric.judge_model_sampling_count or 1) == 1
            and not metric.judge_model_generation_config
            and not metric.judge_model_system_instruction), None) if has_quality else None
        converted = []
        for metric in metrics:
            if getattr(metric, "prompt_template", None) and not getattr(metric, "custom_function", None):
                function = serialized(template_judge(metric), metric.name)
                if metric.name == "refusal_or_action":
                    fallback = function

                    def function(instance, fallback=fallback):
                        if _joint_binary is not None:
                            # The SDK schedules metric columns on worker threads;
                            # wait for this case's quality call before consulting
                            # its second, independently scored joint verdict.
                            _quality_done.setdefault(case_key(instance), threading.Event()).wait(timeout=3600)
                        cached = _joint_results.get(case_key(instance))
                        if cached is not None:
                            print(f"[judge] refusal_or_action: saved joint verdict for {instance.get('eval_case_id')}: {cached['score']}", flush=True)
                            return cached
                        return fallback(instance)
                metric = eval_utils.vertex_types.Metric(name=metric.name, custom_function=function)
                local += 1
            elif getattr(metric, "custom_function", None) and metric.name == "custom_response_quality":
                function = getattr(metric.custom_function, "__wrapped__", metric.custom_function)
                metric.custom_function = serialized(function, metric.name)
            converted.append(metric)
        return converted, local, remote

    eval_utils.prepare_eval_metrics = prepare
