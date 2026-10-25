"""Validate the required evaluation cases and deterministic scoring boundary."""

import json
import runpy
from pathlib import Path

import pytest
import yaml

EVAL = Path(__file__).resolve().parents[1] / "eval"
link_present = runpy.run_path(str(EVAL / "link_presence.py"))["evaluate"]


@pytest.mark.parametrize("case_id,text,expected", [
    ("get_quotation", "http://localhost:3000/quotations/12", 1),
    ("convert_to_order", "http://localhost:3000/orders/13", 1),
    ("get_quotation", "[報價單](http://localhost:3000/quotations/12)", 0),
    ("get_quotation", "查詢成功", 0),
    ("get_quotation", "/quotations/12", 0),
    ("off_topic_weather", "只能處理報價單相關操作", 1),
    ("off_topic_weather", "[連結](http://localhost:3000/quotations/12)", 0),
])
def test_plain_link_metric(case_id, text, expected):
    for response in (text, {"parts": [{"text": text}]}):
        assert link_present({"eval_case_id": case_id, "response": response})["score"] == expected


def test_eval_datasets_and_exact_metric_names():
    actions = json.loads((EVAL / "datasets/quotation-actions.json").read_text(encoding="utf-8"))["eval_cases"]
    assert {case["eval_case_id"] for case in actions} == {
        "get_quotation", "list_customer_quotations", "duplicate_quotation",
        "update_pricing_factor", "adjust_total_price", "convert_to_order",
    }
    guardrails = json.loads((EVAL / "datasets/quotation-guardrails.json").read_text(encoding="utf-8"))["eval_cases"]
    assert {case["eval_case_id"] for case in guardrails} == {
        "off_topic_weather", "off_topic_customer_crud", "clarify_then_complete",
    }
    continuation = next(case for case in guardrails if case["eval_case_id"] == "clarify_then_complete")
    assert "prompt" not in continuation
    turns = continuation["agent_data"]["turns"]
    assert len(turns) == 2
    assert turns[0]["events"][-1]["content"]["parts"][0]["text"].startswith("請提供報價單編號")
    assert all("state_delta" not in event for turn in turns for event in turn["events"])
    assert turns[1]["events"][-1]["author"] == "user"
    config = yaml.safe_load((EVAL / "eval_config.yaml").read_text(encoding="utf-8"))
    assert config["metrics_to_run"] == [
        "custom_response_quality", "link_present", "refusal_or_action", "agent_turn_count",
    ]
    for metric in config["custom_metrics"]:
        if "prompt_template" in metric:
            assert "{prompt}" not in metric["prompt_template"]
            assert "{response}" in metric["prompt_template"]
            assert "{agent_data}" in metric["prompt_template"]
