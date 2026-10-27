from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ezstore_a2a_coordinator.a2a_transport import A2ARemoteUnavailable
from ezstore_a2a_coordinator.dispatch import dispatch_request
from ezstore_a2a_coordinator.intent import CoordinatorIntent
from ezstore_a2a_coordinator.routing import (
    customer_subrequest,
    quotation_subrequest,
    resolve_route,
)


class FakeA2AClient:
    def __init__(self, responses: dict[str, str | Exception] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, str]] = []

    async def send_message(self, agent_name: str, text: str) -> str:
        self.calls.append((agent_name, text))
        result = self.responses.get(agent_name, f"result from {agent_name}")
        if isinstance(result, Exception):
            raise result
        return result


def test_intent_output_is_structured_and_limited_to_routes() -> None:
    intent = CoordinatorIntent(route="combined_cross_agent")
    assert intent.route == "combined_cross_agent"
    with pytest.raises(ValueError):
        CoordinatorIntent(route="direct_backend")


def test_routing_is_guarded_by_allowlisted_read_intents() -> None:
    assert resolve_route(
        "Show me quotation QT-20260330-001.", "quotation_only"
    ) == "quotation_only"
    assert resolve_route(
        "Give me an overview of customer 史塔克工業.", "customer_insight_only"
    ) == "customer_insight_only"
    assert resolve_route(
        "Analyze customer 史塔克工業 and also show quotation QT-20260330-001.",
        "combined_cross_agent",
    ) == "combined_cross_agent"
    assert resolve_route("What is the weather today?", "off_topic") == "off_topic"


@pytest.mark.asyncio
async def test_quotation_only_delegates_via_quotation_specialist() -> None:
    remote = FakeA2AClient({"quotation_agent": "quotation result"})
    response = await dispatch_request(
        "Show me quotation QT-20260330-001.", "quotation_only", remote
    )
    assert response == "quotation result"
    assert remote.calls == [
        (
            "quotation_agent",
            "我要查詢報價單，報價單編號：QT-20260330-001",
        )
    ]


@pytest.mark.asyncio
async def test_customer_insight_only_delegates_via_sales_specialist() -> None:
    remote = FakeA2AClient({"sales_insight_agent": "sales result"})
    prompt = "Give me an overview of customer 史塔克工業."
    response = await dispatch_request(prompt, "customer_insight_only", remote)
    assert response == "sales result"
    assert remote.calls == [("sales_insight_agent", prompt)]


@pytest.mark.asyncio
async def test_combined_cross_agent_invokes_both_and_preserves_results() -> None:
    remote = FakeA2AClient(
        {
            "sales_insight_agent": "customer facts: orders=2",
            "quotation_agent": "quotation facts: QT-20260330-001 total=8000",
        }
    )
    response = await dispatch_request(
        "Analyze customer 史塔克工業 and also show quotation QT-20260330-001.",
        "combined_cross_agent",
        remote,
    )
    assert {name for name, _ in remote.calls} == {
        "sales_insight_agent",
        "quotation_agent",
    }
    assert all("QT-20260330-001" not in prompt for name, prompt in remote.calls if name == "sales_insight_agent")
    assert "customer facts: orders=2" in response
    assert "quotation facts: QT-20260330-001 total=8000" in response


@pytest.mark.asyncio
async def test_reject_write_request_without_remote_calls() -> None:
    remote = FakeA2AClient()
    response = await dispatch_request(
        "Please modify quotation QT-20260330-001.", "quotation_only", remote
    )
    assert "不能新增、修改、刪除" in response
    assert remote.calls == []


@pytest.mark.asyncio
async def test_off_topic_without_remote_calls() -> None:
    remote = FakeA2AClient()
    response = await dispatch_request("What is the weather today?", "off_topic", remote)
    assert "只能協助查詢報價單" in response
    assert remote.calls == []


@pytest.mark.asyncio
async def test_remote_agent_unavailable_has_named_a2a_error_and_no_fallback() -> None:
    remote = FakeA2AClient(
        {"quotation_agent": A2ARemoteUnavailable("quotation_agent", "message exchange")}
    )
    response = await dispatch_request(
        "Show me quotation QT-20260330-001.", "quotation_only", remote
    )
    assert "quotation_agent" in response
    assert "A2A 委派失敗" in response
    assert remote.calls == [
        (
            "quotation_agent",
            "我要查詢報價單，報價單編號：QT-20260330-001",
        )
    ]


@pytest.mark.asyncio
async def test_combined_reports_partial_a2a_failure_without_fallback() -> None:
    remote = FakeA2AClient(
        {
            "sales_insight_agent": "customer result",
            "quotation_agent": A2ARemoteUnavailable("quotation_agent", "discovery"),
        }
    )
    response = await dispatch_request(
        "Analyze customer 史塔克工業 and also show quotation QT-20260330-001.",
        "combined_cross_agent",
        remote,
    )
    assert {name for name, _ in remote.calls} == {
        "sales_insight_agent",
        "quotation_agent",
    }
    assert "customer result" in response
    assert "quotation_agent" in response
    assert "A2A 委派失敗" in response


def test_coordinator_has_no_backend_or_mcp_business_client_imports() -> None:
    source_root = Path(__file__).resolve().parents[2] / "ezstore_a2a_coordinator"
    imported_modules: list[str] = []
    for source in source_root.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
    assert not any(
        name == "backend" or name.startswith("backend.") or name == "mcp" or name.startswith("mcp.")
        for name in imported_modules
    )


def test_a2a_subrequest_builders_keep_only_their_delegated_scope() -> None:
    message = "Analyze customer 史塔克工業 and also show quotation QT-20260330-001."
    assert quotation_subrequest(message) == (
        "我要查詢報價單，報價單編號：QT-20260330-001"
    )
    assert customer_subrequest(message) == "Analyze customer 史塔克工業"
