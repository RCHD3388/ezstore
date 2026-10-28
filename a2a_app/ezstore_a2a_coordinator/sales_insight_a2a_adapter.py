"""A2A server adapter for the unchanged Sales Insight ADK workflow.

The standard ADK A2A event converter can terminate the Workflow Task without
exposing its final ``result`` state as user-facing text. This executor runs the
same ADK app and publishes that final value as a normal A2A text artifact and
completed status message.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from google.genai import types

from ezstore_a2a_coordinator.routing import is_write_request


_CUSTOMER = re.compile(r"customer|客戶", re.IGNORECASE)
_OVERVIEW = re.compile(r"overview|概況|總覽|总览", re.IGNORECASE)
_OTHER_INSIGHT = re.compile(
    r"history|歷史|compare|comparison|比較|对比|conversion|轉換|转换|"
    r"QT-\d{8}-\d{3}|quotation\s+list|報價清單",
    re.IGNORECASE,
)
_EXTRA_WRITE = re.compile(r"\b(?:add|change|save|place)\b|新增|變更|变更", re.IGNORECASE)
_WRITE_REFUSAL = "This A2A service is read-only. Business changes are not available."
_SCOPE_REFUSAL = "This A2A service supports Customer Overview only."


def _allowed_request(text: str) -> bool:
    """Expose only the existing Customer Overview workflow operation."""
    return bool(
        _CUSTOMER.search(text)
        and _OVERVIEW.search(text)
        and not _OTHER_INSIGHT.search(text)
    )


def _event_text(event: Any) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    return "\n".join(
        str(part.text)
        for part in parts
        if getattr(part, "text", None)
    ).strip()


def _final_workflow_text(events: list[Any]) -> str:
    """Select the Workflow's business result, excluding classifier output."""
    result = ""
    final_content = ""
    for event in events:
        actions = getattr(event, "actions", None)
        delta = getattr(actions, "state_delta", None) or {}
        candidate = delta.get("result")
        if isinstance(candidate, str) and candidate.strip():
            result = candidate.strip()
        if getattr(event, "is_final_response", lambda: False)():
            final_content = _event_text(event)
    if result:
        return result
    if final_content:
        return final_content
    raise RuntimeError("Sales Insight Workflow completed without a final result.")


class SalesInsightA2AAdapter(AgentExecutor):
    """Expose an existing ADK Runner as an A2A specialist with final text."""

    def __init__(self, runner: Any, *, app_name: str, user_id: str = "a2a-user"):
        self._runner = runner
        self._app_name = app_name
        self._user_id = user_id

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        request_text = context.get_user_input().strip()
        if not request_text:
            raise ValueError("A2A request must contain user text.")

        session_id = context.context_id or uuid.uuid4().hex
        if is_write_request(request_text) or _EXTRA_WRITE.search(request_text):
            response_text = _WRITE_REFUSAL
        elif not _allowed_request(request_text):
            response_text = _SCOPE_REFUSAL
        else:
            events = [
                event
                async for event in self._runner.run_async(
                    user_id=self._user_id,
                    session_id=session_id,
                    new_message=types.Content(
                        role="user", parts=[types.Part(text=request_text)]
                    ),
                )
            ]
            response_text = _final_workflow_text(events)
        task_id = context.task_id or uuid.uuid4().hex
        context_id = context.context_id or session_id
        response_message = Message(
            message_id=uuid.uuid4().hex,
            role=Role.ROLE_AGENT,
            parts=[Part(text=response_text)],
            task_id=task_id,
            context_id=context_id,
        )

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id=uuid.uuid4().hex,
                    parts=[Part(text=response_text)],
                ),
                last_chunk=True,
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_COMPLETED,
                    message=response_message,
                ),
            )
        )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        del context, event_queue
        return None


async def create_sales_insight_a2a_app():
    """Build the standalone A2A FastAPI service around the existing workflow."""
    import sys
    from pathlib import Path

    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import (
        add_a2a_routes_to_fastapi,
        create_agent_card_routes,
        create_jsonrpc_routes,
    )
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
    from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
    from dotenv import load_dotenv
    from fastapi import FastAPI
    from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    project_root = Path(__file__).resolve().parents[2]
    agent2_root = project_root / "agent2"
    load_dotenv(project_root / ".env")
    load_dotenv(agent2_root / ".env", override=False)
    if str(agent2_root) not in sys.path:
        sys.path.insert(0, str(agent2_root))

    from sales_insight_agent.agent import app as adk_app  # noqa: PLC0415
    from sales_insight_agent.agent import root_agent  # noqa: PLC0415

    runner = Runner(
        app=adk_app,
        session_service=InMemorySessionService(),
        auto_create_session=True,
    )
    executor = SalesInsightA2AAdapter(runner, app_name=adk_app.name)
    rpc_path = "/a2a/sales_insight_agent"
    base_url = "http://127.0.0.1:8012"
    card = await AgentCardBuilder(
        agent=root_agent,
        capabilities=AgentCapabilities(streaming=False),
        rpc_url=f"{base_url}{rpc_path}",
        agent_version="0.1.0",
    ).build()
    card.skills.clear()
    card.skills.append(
        AgentSkill(
            id="customer_overview",
            name="Customer Overview",
            description="Read-only customer sales overview from the existing Sales Insight Agent.",
            tags=["customer", "sales", "read-only"],
            examples=["Give me an overview of customer 史塔克工業."],
        )
    )
    if not any(i.protocol_binding == "JSONRPC" for i in card.supported_interfaces):
        card.supported_interfaces.append(
            AgentInterface(
                protocol_binding="JSONRPC",
                protocol_version="1.0",
                url=f"{base_url}{rpc_path}",
            )
        )
    if not card.supported_interfaces:
        card.supported_interfaces.append(
            AgentInterface(
                protocol_binding="JSONRPC",
                protocol_version="1.0",
                url=f"{base_url}{rpc_path}",
            )
        )

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    service = FastAPI(title="sales-insight-agent-a2a-adapter")
    add_a2a_routes_to_fastapi(
        service,
        agent_card_routes=create_agent_card_routes(
            card,
            card_url=AGENT_CARD_WELL_KNOWN_PATH,
        ),
        jsonrpc_routes=create_jsonrpc_routes(
            request_handler,
            rpc_url=rpc_path,
        ),
    )
    service.state.runner = runner
    return service


def main() -> None:
    import asyncio

    import uvicorn

    service = asyncio.run(create_sales_insight_a2a_app())
    uvicorn.run(service, host="0.0.0.0", port=8012)


if __name__ == "__main__":
    main()
