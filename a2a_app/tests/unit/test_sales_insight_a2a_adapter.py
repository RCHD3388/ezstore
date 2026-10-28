from __future__ import annotations

from types import SimpleNamespace

import pytest
import httpx
from a2a.types import TaskArtifactUpdateEvent, TaskState, TaskStatusUpdateEvent

from ezstore_a2a_coordinator.sales_insight_a2a_adapter import (
    SalesInsightA2AAdapter,
    _final_workflow_text,
    create_sales_insight_a2a_app,
)


def _adk_event(*, state_delta=None, text="", final=False):
    return SimpleNamespace(
        actions=SimpleNamespace(state_delta=state_delta or {}),
        content=SimpleNamespace(parts=[SimpleNamespace(text=text)] if text else []),
        is_final_response=lambda: final,
    )


def test_prefers_workflow_business_result_over_classifier_output() -> None:
    events = [
        _adk_event(state_delta={"intent": '{"action":"customer_overview"}'}),
        _adk_event(state_delta={"result": "Customer overview: orders=2"}),
        _adk_event(text="respond node", final=True),
    ]

    assert _final_workflow_text(events) == "Customer overview: orders=2"


def test_uses_final_adk_response_content_when_result_state_is_absent() -> None:
    assert _final_workflow_text([_adk_event(text="Final business answer", final=True)]) == (
        "Final business answer"
    )


def test_requires_a_user_facing_workflow_result() -> None:
    with pytest.raises(RuntimeError, match="without a final result"):
        _final_workflow_text([_adk_event(state_delta={"intent": "{}"})])


class _Runner:
    def __init__(self):
        self.calls = []

    async def run_async(self, **kwargs):
        self.calls.append(kwargs["new_message"].parts[0].text)
        yield _adk_event(state_delta={"result": "Grounded overview"})


class _Queue:
    def __init__(self):
        self.events = []

    async def enqueue_event(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_adapter_publishes_result_as_final_artifact_and_status_message() -> None:
    runner = _Runner()
    adapter = SalesInsightA2AAdapter(runner, app_name="sales_insight_agent")
    context = SimpleNamespace(
        get_user_input=lambda: "Give me an overview of customer 史塔克工業.",
        context_id="context-1",
        task_id="task-1",
    )
    queue = _Queue()

    await adapter.execute(context, queue)

    assert len(queue.events) == 2
    artifact_event, status_event = queue.events
    assert isinstance(artifact_event, TaskArtifactUpdateEvent)
    assert artifact_event.artifact.parts[0].text == "Grounded overview"
    assert artifact_event.last_chunk
    assert isinstance(status_event, TaskStatusUpdateEvent)
    assert status_event.status.message.parts[0].text == "Grounded overview"
    assert TaskState.Name(status_event.status.state) == "TASK_STATE_COMPLETED"
    assert runner.calls == ["Give me an overview of customer 史塔克工業."]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("List customer 史塔克工業 order history.", "Customer Overview only"),
        ("Give me an overview and order history for customer 史塔克工業.", "Customer Overview only"),
        ("What is the weather?", "Customer Overview only"),
        ("Please modify customer 史塔克工業 overview.", "read-only"),
        ("Please change customer 史塔克工業 overview.", "read-only"),
        ("Duplicate quotation QT-20260330-001.", "read-only"),
    ],
)
async def test_adapter_refuses_out_of_scope_and_write_without_running_agent(prompt, expected):
    runner = _Runner()
    adapter = SalesInsightA2AAdapter(runner, app_name="sales_insight_agent")
    context = SimpleNamespace(
        get_user_input=lambda: prompt, context_id="context-2", task_id="task-2"
    )
    queue = _Queue()

    await adapter.execute(context, queue)

    assert runner.calls == []
    assert len(queue.events) == 2
    assert expected in queue.events[0].artifact.parts[0].text
    assert queue.events[1].status.message.parts[0].text == queue.events[0].artifact.parts[0].text


@pytest.mark.asyncio
async def test_agent_card_advertises_only_customer_overview():
    service = await create_sales_insight_a2a_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=service), base_url="http://127.0.0.1:8012"
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "sales_insight_agent"
    assert [skill["id"] for skill in card["skills"]] == ["customer_overview"]
    assert any(
        interface["protocolBinding"] == "JSONRPC"
        and interface["url"] == "http://127.0.0.1:8012/a2a/sales_insight_agent"
        for interface in card["supportedInterfaces"]
    )
