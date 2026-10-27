from __future__ import annotations

from types import SimpleNamespace

import pytest
from a2a.types import TaskArtifactUpdateEvent, TaskState, TaskStatusUpdateEvent

from ezstore_a2a_coordinator.sales_insight_a2a_adapter import (
    SalesInsightA2AAdapter,
    _final_workflow_text,
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
    async def run_async(self, **kwargs):
        assert kwargs["new_message"].parts[0].text == "overview request"
        yield _adk_event(state_delta={"result": "Grounded overview"})


class _Queue:
    def __init__(self):
        self.events = []

    async def enqueue_event(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_adapter_publishes_result_as_final_artifact_and_status_message() -> None:
    adapter = SalesInsightA2AAdapter(_Runner(), app_name="sales_insight_agent")
    context = SimpleNamespace(
        get_user_input=lambda: "overview request",
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
