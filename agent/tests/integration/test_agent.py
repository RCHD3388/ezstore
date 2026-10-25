"""Graph event contracts without an external model or MCP connection."""

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from quotation_agent.agent import app


@pytest.mark.asyncio
@pytest.mark.parametrize("message, expected", [
    ("今天天氣如何？", "只能處理報價單"),
    ("我要查詢報價單", "尚未設定模型憑證"),
])
async def test_graph_emits_respond_without_credentials(monkeypatch, message, expected):
    monkeypatch.setattr("quotation_agent.agent.credentials_configured", lambda: False)
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(app_name=app.name, user_id="test_user")
    events = [event async for event in runner.run_async(
        user_id="test_user", session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text=message)]),
    )]
    replies = [event for event in events if event.node_info.name == "respond"]
    assert len(replies) == 1
    assert expected in replies[0].content.parts[0].text
    assert all(not event.get_function_calls() for event in events)
    assert all(not event.error_code for event in events)
    await runner.close()
