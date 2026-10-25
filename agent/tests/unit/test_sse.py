"""Transport checks: idle streams survive proxies and clean up on exit."""

import asyncio

import pytest

from quotation_agent.app_utils.sse import SseHeartbeatMiddleware


@pytest.mark.asyncio
async def test_idle_stream_keeps_exact_adk_events_and_stops_heartbeats():
    messages = []
    ping_received = asyncio.Event()
    payload = b'data: {"nodeInfo":{"path":"quotation_agent/respond@1"}}\n\n'

    async def send(message):
        messages.append(message)
        if message.get("body", b"").startswith(b":"):
            ping_received.set()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream; charset=utf-8")]})
        await asyncio.wait_for(ping_received.wait(), timeout=1)
        await send({"type": "http.response.body", "body": payload, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    await SseHeartbeatMiddleware(app, interval=0.001)(
        {"type": "http", "path": "/run_sse"}, None, send,
    )
    size = len(messages)
    await asyncio.sleep(0.01)
    assert len(messages) == size
    bodies = [message["body"] for message in messages if message["type"] == "http.response.body"]
    assert b"".join(body for body in bodies if not body.startswith(b":")) == payload
    assert bodies[-1] == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("path,content_type", [
    ("/list-apps", b"application/json"),
    ("/run_sse", b"application/json"),
    ("/other-stream", b"text/event-stream"),
])
async def test_other_responses_are_untouched(path, content_type):
    messages = []
    expected = [
        {"type": "http.response.start", "status": 422, "headers": [(b"content-type", content_type)]},
        {"type": "http.response.body", "body": b"unchanged", "more_body": False},
    ]

    async def send(message):
        messages.append(message)

    async def app(scope, receive, send):
        await send(expected[0])
        await asyncio.sleep(0.01)
        await send(expected[1])

    await SseHeartbeatMiddleware(app, interval=0.001)(
        {"type": "http", "path": path}, None, send,
    )
    assert messages == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_heartbeats_stop_on_error_or_disconnect(failure):
    messages = []
    ping_received = asyncio.Event()

    async def send(message):
        messages.append(message)
        if message.get("body", b"").startswith(b":"):
            ping_received.set()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        await asyncio.wait_for(ping_received.wait(), timeout=1)
        raise failure()

    with pytest.raises(failure):
        await SseHeartbeatMiddleware(app, interval=0.001)(
            {"type": "http", "path": "/run_sse"}, None, send,
        )
    size = len(messages)
    await asyncio.sleep(0.01)
    assert len(messages) == size
