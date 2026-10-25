"""Keep the Chat UI stream open while the model waits or backs off."""

import asyncio
from contextlib import suppress

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SseHeartbeatMiddleware:
    """Send SSE comments without changing ADK events or moving their producer."""

    def __init__(self, app: ASGIApp, interval: float = 15) -> None:
        self.app = app
        self.interval = interval

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != "/run_sse":
            await self.app(scope, receive, send)
            return

        lock = asyncio.Lock()
        active = False
        heartbeat_task = None

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(self.interval)
                async with lock:
                    if not active:
                        return
                    await send({
                        "type": "http.response.body",
                        "body": b": keep-alive\n\n",
                        "more_body": True,
                    })

        async def send_with_heartbeat(message: Message) -> None:
            nonlocal active, heartbeat_task
            async with lock:
                if message["type"] == "http.response.start":
                    active = any(
                        name.lower() == b"content-type"
                        and value.lower().startswith(b"text/event-stream")
                        for name, value in message.get("headers", [])
                    )
                    await send(message)
                    if active:
                        heartbeat_task = asyncio.create_task(heartbeat())
                    return
                if message["type"] == "http.response.body" and not message.get("more_body", False):
                    active = False
                await send(message)

        try:
            await self.app(scope, receive, send_with_heartbeat)
        finally:
            active = False
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task
