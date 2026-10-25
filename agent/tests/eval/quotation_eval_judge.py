"""Run the configured rubrics against a real model, with serialized requests."""

import json
import os
import threading
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

_local = threading.local()
_lock = threading.Lock()
_last_request = 0.0
_config_path = Path(__file__).with_name("eval_config.yaml")
_config = yaml.safe_load(_config_path.read_text(encoding="utf-8"))
_templates = {metric["name"]: metric["prompt_template"]
              for metric in _config["custom_metrics"] if "prompt_template" in metric}
_agent_dir = _config_path.parents[2]
load_dotenv(_agent_dir / ".env", override=False)
load_dotenv(_agent_dir.parent / ".env", override=False)


class Verdict(BaseModel):
    score: int
    explanation: str


def _client():
    if not hasattr(_local, "client"):
        _local.client = genai.Client(http_options=types.HttpOptions(
            timeout=120000,
            retry_options=types.HttpRetryOptions(
                attempts=3, initial_delay=30, max_delay=120, exp_base=2,
            ),
        ))
    return _local.client


def judge(instance, name, *, minimum, maximum):
    global _last_request
    prompt = _templates[name]
    for field in ("response", "agent_data"):
        prompt = prompt.replace("{" + field + "}", json.dumps(instance.get(field), ensure_ascii=False))
    if instance.get("reference"):
        prompt += "\n正確回覆的參考標準：" + json.dumps(instance["reference"], ensure_ascii=False)
    # The SDK may grade cases on worker threads. Serialize both judge metrics and
    # leave 30 seconds between requests, including retries by the CLI wrapper.
    with _lock:
        time.sleep(max(0, 30 - (time.monotonic() - _last_request)))
        try:
            response = _client().models.generate_content(
                model=os.getenv("AGENT_MODEL", "gemini-3.8-flash"),
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
                    response_mime_type="application/json",
                    response_json_schema=Verdict.model_json_schema(),
                ),
            )
            verdict = Verdict.model_validate_json(response.text)
            if not minimum <= verdict.score <= maximum:
                raise ValueError(f"Judge score outside {minimum}–{maximum}: {verdict.score}")
            return verdict.model_dump()
        finally:
            _last_request = time.monotonic()
