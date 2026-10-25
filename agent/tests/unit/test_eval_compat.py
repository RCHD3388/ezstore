"""The AI Studio transport must preserve rubrics and never invent scores."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval_compat"))
import ai_studio_eval as compat
from pydantic import BaseModel


def test_judge_defaults_keep_explicit_settings_and_do_not_mutate_the_caller():
    original = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
    configured = compat.judge_config(original)
    assert original.thinking_config is None
    assert configured.temperature == 0
    assert configured.response_mime_type == "application/json"
    assert configured.thinking_config.thinking_level == types.ThinkingLevel.LOW
    explicit = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="HIGH"))
    assert compat.judge_config(explicit).thinking_config.thinking_level == types.ThinkingLevel.HIGH


def test_cloud_client_is_lazy_and_authentication_errors_still_propagate():
    calls = []

    class CloudHelper:
        pass

    def factory(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("real cloud access needs credentials")

    compat.lazy_cloud_client(CloudHelper, "storage_client", factory)
    api_client = SimpleNamespace(project=None, _credentials=None)
    helper = CloudHelper(api_client)
    assert calls == []
    with pytest.raises(RuntimeError, match="needs credentials"):
        _ = helper.storage_client
    assert calls == [{"project": None, "credentials": None}]


@pytest.mark.parametrize("score", [0, 1])
def test_template_uses_original_rubric_and_actual_model_verdict(monkeypatch, score):
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=json.dumps({"score": score, "explanation": "actual verdict"}))

    monkeypatch.setattr(compat, "_client", SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    metric = SimpleNamespace(
        name="refusal_or_action", prompt_template='Original rule. Response: {response}; trace: {agent_data}. Return {"score": 0 or 1}.',
        judge_model="gemini-3.8-flash", judge_model_sampling_count=1,
        judge_model_generation_config={}, judge_model_system_instruction=None,
    )
    instance = {"response": {"parts": [{"text": "response"}]}, "agent_data": {"turns": []}}
    verdict = compat.template_judge(metric)(instance)
    assert verdict == {"score": score, "explanation": "actual verdict"}
    expected = metric.prompt_template.replace("{response}", json.dumps(instance["response"], ensure_ascii=False))
    expected = expected.replace("{agent_data}", json.dumps(instance["agent_data"], ensure_ascii=False))
    assert calls[0]["contents"] == expected
    assert calls[0]["model"] == "gemini-3.8-flash"


def test_judge_failure_does_not_become_a_passing_or_zero_score(monkeypatch):
    def generate(**kwargs):
        raise TimeoutError("upstream unavailable")

    monkeypatch.setattr(compat, "_client", SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    metric = SimpleNamespace(
        name="refusal_or_action", prompt_template="{response}", judge_model="gemini-3.8-flash",
        judge_model_sampling_count=1, judge_model_generation_config={}, judge_model_system_instruction=None,
    )
    with pytest.raises(TimeoutError):
        compat.template_judge(metric)({"response": "test"})


@pytest.mark.parametrize("quality,binary", [(5, 1), (1, 0), (4, 0)])
def test_joint_call_preserves_both_prompts_and_projects_actual_verdicts(monkeypatch, quality, binary):
    class OriginalVerdict(BaseModel):
        score: int
        explanation: str

    instance = {"eval_case_id": "case", "response": {"parts": [{"text": "actual response"}]}, "agent_data": {"turns": []}}
    binary_metric = SimpleNamespace(judge_model="gemini-3.8-flash", prompt_template="ORIGINAL BINARY RULE: {response} {agent_data}")
    monkeypatch.setattr(compat, "_joint_binary", binary_metric)
    monkeypatch.setattr(compat, "_joint_results", {})
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[types.Part.from_text(
            text=json.dumps({"quality": {"score": quality, "explanation": "quality reason"},
                             "refusal_or_action": {"score": binary, "explanation": "binary reason"}}),
        )]))])

    config = types.GenerateContentConfig(response_schema=OriginalVerdict, temperature=0)
    token = compat._quality_instance.set(instance)
    try:
        response = compat.joint_generate(generate, (), {
            "model": "gemini-3.8-flash", "contents": "ORIGINAL QUALITY RULE", "config": config,
        })
    finally:
        compat._quality_instance.reset(token)
    assert len(calls) == 1
    assert "ORIGINAL QUALITY RULE" in calls[0]["contents"]
    assert compat.render(binary_metric.prompt_template, instance) in calls[0]["contents"]
    assert response.parsed.score == quality
    assert json.loads(response.text)["score"] == quality
    assert compat._joint_results[compat.case_key(instance)] == {"score": binary, "explanation": "binary reason"}
    assert config.response_schema is OriginalVerdict
    assert config.response_json_schema is None


def test_joint_cache_is_specific_to_actual_response_and_trace():
    assert compat.case_key({"response": "one"}) != compat.case_key({"response": "two"})
