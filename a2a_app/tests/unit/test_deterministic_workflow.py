"""Exercise the Coordinator graph without a model or remote service."""

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ezstore_a2a_coordinator import workflow
from ezstore_a2a_coordinator.dispatch import OFF_TOPIC_REFUSAL, WRITE_REFUSAL


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "expected_route", "expected_reply"),
    [
        ("Show me quotation QT-20260330-001.", "quotation_only", "remote result"),
        (
            "Give me an overview of customer 史塔克工業.",
            "customer_insight_only",
            "remote result",
        ),
        (
            "Analyze customer 史塔克工業 and also show quotation QT-20260330-001.",
            "combined_cross_agent",
            "remote result",
        ),
        (
            "Analyze customer 史塔克工業 and duplicate quotation QT-20260330-001.",
            "write_request",
            WRITE_REFUSAL,
        ),
        ("What is the weather today?", "off_topic", OFF_TOPIC_REFUSAL),
    ],
)
async def test_graph_routes_without_llm(
    monkeypatch, prompt, expected_route, expected_reply
):
    calls = []

    async def dispatch(message, route):
        calls.append((message, route))
        return "remote result"

    monkeypatch.setattr(workflow, "dispatch_request", dispatch)
    sessions = InMemorySessionService()
    runner = Runner(
        agent=workflow.build_workflow(),
        app_name="ezstore_a2a_coordinator",
        session_service=sessions,
        auto_create_session=True,
    )
    events = [
        event
        async for event in runner.run_async(
            user_id="test-user",
            session_id="test-session",
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        )
    ]
    session = await sessions.get_session(
        app_name="ezstore_a2a_coordinator", user_id="test-user", session_id="test-session"
    )
    assert session.state["resolved_route"] == expected_route
    assert any(
        part.text == expected_reply
        for event in events
        for part in (event.content.parts if event.content else [])
    )
    assert calls == (
        [] if expected_route in {"write_request", "off_topic"}
        else [(prompt, expected_route)]
    )
