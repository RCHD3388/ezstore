from __future__ import annotations

import pytest
from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

from ezstore_a2a_coordinator.a2a_transport import (
    A2ARemoteUnavailable,
    _extract_response,
)


def test_accepts_direct_agent_message_without_task_state() -> None:
    response = StreamResponse(
        message=Message(role=Role.ROLE_AGENT, parts=[Part(text="direct answer")])
    )

    assert _extract_response([response], "sales_insight_agent") == "direct answer"


def test_extracts_completed_task_status_message_artifacts_and_history() -> None:
    response = Task(
        status=TaskStatus(
            state=TaskState.TASK_STATE_COMPLETED,
            message=Message(parts=[Part(text="status answer")]),
        ),
        artifacts=[Artifact(parts=[Part(text="artifact answer")])],
        history=[Message(role=Role.ROLE_AGENT, parts=[Part(text="history answer")])],
    )

    assert _extract_response([response], "sales_insight_agent") == (
        "status answer\nartifact answer\nhistory answer"
    )


def test_extracts_final_text_from_completed_status_update() -> None:
    response = StreamResponse(
        status_update=TaskStatusUpdateEvent(
            status=TaskStatus(
                state=TaskState.TASK_STATE_COMPLETED,
                message=Message(parts=[Part(text="status update answer")]),
            )
        )
    )

    assert _extract_response([response], "sales_insight_agent") == "status update answer"


def test_extracts_final_text_from_artifact_update_before_completed_status() -> None:
    responses = [
        StreamResponse(
            artifact_update=TaskArtifactUpdateEvent(
                artifact=Artifact(parts=[Part(text="artifact update answer")]),
                last_chunk=True,
            )
        ),
        StreamResponse(
            status_update=TaskStatusUpdateEvent(
                status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED)
            )
        ),
    ]

    assert _extract_response(responses, "sales_insight_agent") == "artifact update answer"


def test_does_not_return_classifier_payload_as_a_completed_answer() -> None:
    payload = '{"action":"customer_overview","customer_names":[]}'
    responses = [
        StreamResponse(
            artifact_update=TaskArtifactUpdateEvent(
                artifact=Artifact(parts=[Part(text=payload)]), last_chunk=True
            )
        ),
        StreamResponse(
            status_update=TaskStatusUpdateEvent(
                status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED)
            )
        ),
    ]

    with pytest.raises(A2ARemoteUnavailable, match="message exchange"):
        _extract_response(responses, "sales_insight_agent")
