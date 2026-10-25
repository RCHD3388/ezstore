"""Deterministic policy/graph contracts; these do not grade LLM responses."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from google.adk.events import Event
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from quotation_agent.agent import (
    before_classification, classification_error, clarify, respond, route_intent, root_agent, service_error,
)
from quotation_agent.policy import PENDING_KEY, clarification_history, tool_arguments
from quotation_agent.schemas import QuotationIntent


def context(text, state=None):
    return SimpleNamespace(
        user_content=types.Content(role="user", parts=[types.Part.from_text(text=text)]),
        state=state if state is not None else {},
    )


@pytest.mark.asyncio
async def test_router_blocks_off_topic_even_if_classifier_suggests_action():
    intent = QuotationIntent(intent="duplicate_quotation", quotation_number="QT-20260330-001")
    event = await route_intent(context("請新增客戶，也複製報價單"), intent)
    assert event.actions.route == "refuse"


@pytest.mark.asyncio
async def test_clarification_persists_and_merges_only_pending_fields():
    state = {}
    first = QuotationIntent(intent="update_pricing_factor", new_pricing_factor=1.5)
    route = await route_intent(context("我要修改報價單報價因子為 1.5", state), first)
    assert route.actions.route == "clarify"
    state.update(route.actions.state_delta)
    clarification = await clarify(context("", state), first)
    state.update(clarification.actions.state_delta)
    completed = await route_intent(context("QT-20260330-001", state), QuotationIntent(
        intent="provide_details", quotation_number="QT-20260330-001",
    ))
    assert completed.actions.route == "update_pricing_factor"
    assert completed.output["new_pricing_factor"] == 1.5
    assert completed.actions.state_delta[PENDING_KEY] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
async def test_nonpositive_or_nonfinite_pricing_never_reaches_tool(value):
    event = await route_intent(context("修改報價單報價因子"), QuotationIntent(
        intent="update_pricing_factor", quotation_number="QT-20260330-001", new_pricing_factor=value,
    ))
    assert event.actions.route == "clarify"


def test_arguments_are_limited_to_operation_schema():
    intent = QuotationIntent(intent="get_quotation", quotation_number="QT-20260330-001", customer_name="irrelevant")
    assert tool_arguments(intent) == {"quotation_number": "QT-20260330-001"}


def test_missing_credentials_short_circuits_model_request():
    with patch("quotation_agent.agent.credentials_configured", return_value=False):
        result = before_classification(context("查詢報價單"), LlmRequest())
    parsed = QuotationIntent.model_validate_json(result.content.parts[0].text)
    assert parsed.intent == "service_error"
    assert parsed.error_reason == "missing_credentials"


def restored_context(message, last_response="請提供新的報價因子（大於 0 的數值），我會接續完成這項報價單操作。"):
    ctx = context(message)
    ctx.session = SimpleNamespace(events=[
        Event(author="user", content=types.Content(role="user", parts=[types.Part.from_text(
            text="我要修改報價單報價因子，報價單編號：QT-20260330-001",
        )])),
        Event(author="quotation_agent", content=types.Content(role="model", parts=[types.Part.from_text(text=last_response)])),
        Event(author="user", content=ctx.user_content),
    ])
    return ctx


@pytest.mark.asyncio
async def test_restored_history_is_classifier_context_without_injecting_session_actions():
    import json

    ctx = restored_context("1.5")
    request = LlmRequest()
    with patch("quotation_agent.agent.credentials_configured", return_value=True):
        assert before_classification(ctx, request) is None
    payload = json.loads(request.contents[0].parts[0].text)
    assert payload["pending_request"] is None
    assert "QT-20260330-001" in payload["clarification_history"]["request"]
    assert PENDING_KEY not in ctx.state
    event = await route_intent(ctx, QuotationIntent(
        intent="update_pricing_factor", quotation_number="QT-20260330-001", new_pricing_factor=1.5,
    ))
    assert event.actions.route == "update_pricing_factor"


def test_restored_history_does_not_bypass_off_topic_refusal():
    response = before_classification(restored_context("今天天氣如何？"), LlmRequest())
    assert QuotationIntent.model_validate_json(response.content.parts[0].text).intent == "off_topic"


def test_completed_history_does_not_reopen_a_pending_operation():
    assert clarification_history(restored_context("1.5", last_response="已完成修改。")) is None


@pytest.mark.asyncio
async def test_respond_preserves_tool_text_exactly():
    text = "原始報價單（未修改）\n系統連結: http://localhost:3000/quotations/12"
    event = await respond(text)
    assert event.content.parts[0].text == text
    assert event.output == text


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [503, 504, None])
async def test_capacity_error_produces_no_action_message(status_code):
    class CapacityError(Exception):
        pass

    if status_code is None:
        error = TimeoutError("upstream timeout")
    else:
        error = CapacityError("upstream unavailable")
        error.code = status_code
    response = classification_error(context("查詢報價單"), LlmRequest(), error)
    intent = QuotationIntent.model_validate_json(response.content.parts[0].text)
    assert intent.error_reason == "model_busy"
    reply = await service_error(context(""), intent)
    assert "繁忙或逾時" in reply
    assert "尚未呼叫任何報價單工具" in reply


def test_graph_has_exactly_one_llm_and_respond_as_only_terminal():
    from google.adk.agents import LlmAgent

    graph = root_agent.graph
    assert sum(isinstance(node, LlmAgent) for node in graph.nodes) == 1
    sources = {edge.from_node.name for edge in graph.edges}
    assert {node.name for node in graph.nodes} - sources == {"respond"}
