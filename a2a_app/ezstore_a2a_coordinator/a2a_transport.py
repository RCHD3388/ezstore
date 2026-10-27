"""A2A Agent Card discovery and JSON-RPC message exchange."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
)

from ezstore_a2a_coordinator.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteAgent:
    name: str
    card_url: str


class A2ARemoteUnavailable(RuntimeError):
    """A remote A2A specialist could not be discovered or complete a task."""

    def __init__(self, agent_name: str, phase: str):
        self.agent_name = agent_name
        self.phase = phase
        super().__init__(f"{agent_name} unavailable during A2A {phase}.")


def _card_location(card_url: str) -> tuple[str, str]:
    parsed = urlsplit(card_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Agent Card URL must be an absolute HTTP(S) URL.")
    base_url = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    card_path = parsed.path or "/.well-known/agent-card.json"
    return base_url, card_path


def _text_parts(message: Any) -> list[str]:
    return [part.text for part in getattr(message, "parts", []) if getattr(part, "text", "")]


def _is_classifier_payload(text: str) -> bool:
    candidate = text.lstrip()
    return candidate.startswith("{") and any(
        marker in candidate[:160] for marker in ('"route"', '"action"')
    )


def _state_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    try:
        return TaskState.Name(value)
    except (TypeError, ValueError):
        return None


def _stream_field(event: Any, field: str, expected_type: type[Any]) -> Any | None:
    """Unwrap one A2A stream field while also accepting direct SDK objects."""
    if isinstance(event, expected_type):
        return event
    has_field = getattr(event, "HasField", None)
    if callable(has_field):
        try:
            return getattr(event, field) if has_field(field) else None
        except (ValueError, TypeError):
            return None
    value = getattr(event, field, None)
    return value if isinstance(value, expected_type) else None


def _is_remote_message(message: Any) -> bool:
    role = getattr(message, "role", None)
    if role == Role.ROLE_AGENT:
        return True
    if role == Role.ROLE_USER:
        return False
    try:
        return Role.Name(role) != "ROLE_USER"
    except (TypeError, ValueError):
        return True


def _extract_response(events: Iterable[Any], agent_name: str) -> str:
    """Extract final text from A2A Message, Task, status, or artifact forms."""
    result_parts: list[str] = []
    terminal_state: str | None = None
    direct_message = False

    def observe_state(value: Any) -> str | None:
        nonlocal terminal_state
        state = _state_name(value)
        if state in {
            "TASK_STATE_COMPLETED",
            "TASK_STATE_FAILED",
            "TASK_STATE_REJECTED",
            "TASK_STATE_CANCELED",
        }:
            terminal_state = state
        return state

    def add_message(message: Any, *, status_message: bool = False) -> None:
        nonlocal direct_message
        if status_message or _is_remote_message(message):
            text = _text_parts(message)
            if text and not status_message:
                direct_message = True
            result_parts.extend(text)

    for event in events:
        message = _stream_field(event, "message", Message)
        if message is not None:
            add_message(message)

        task = _stream_field(event, "task", Task)
        if task is not None:
            state = observe_state(task.status.state)
            if state == "TASK_STATE_COMPLETED":
                add_message(task.status.message, status_message=True)
                for artifact in task.artifacts:
                    result_parts.extend(_text_parts(artifact))
                for history_message in task.history:
                    if _is_remote_message(history_message):
                        result_parts.extend(_text_parts(history_message))

        status_update = _stream_field(
            event, "status_update", TaskStatusUpdateEvent
        )
        if status_update is not None:
            state = observe_state(status_update.status.state)
            if state == "TASK_STATE_COMPLETED":
                add_message(status_update.status.message, status_message=True)

        artifact_update = _stream_field(
            event, "artifact_update", TaskArtifactUpdateEvent
        )
        if artifact_update is not None:
            result_parts.extend(_text_parts(artifact_update.artifact))

    if terminal_state in {
        "TASK_STATE_FAILED",
        "TASK_STATE_REJECTED",
        "TASK_STATE_CANCELED",
    }:
        raise A2ARemoteUnavailable(agent_name, "message exchange")

    cleaned = [
        part.strip()
        for part in result_parts
        if part.strip() and not _is_classifier_payload(part)
    ]
    unique_parts = list(dict.fromkeys(cleaned))
    if not unique_parts or (terminal_state != "TASK_STATE_COMPLETED" and not direct_message):
        raise A2ARemoteUnavailable(agent_name, "message exchange")
    return "\n".join(unique_parts)


class A2ARemoteClient:
    """Resolve configured Agent Cards, then delegate only via the A2A SDK."""

    def __init__(self, agents: dict[str, RemoteAgent] | None = None):
        self.agents = agents or {
            "quotation_agent": RemoteAgent(
                "quotation_agent", settings.quotation_agent_card_url
            ),
            "sales_insight_agent": RemoteAgent(
                "sales_insight_agent", settings.sales_insight_agent_card_url
            ),
        }

    async def send_message(self, agent_name: str, text: str) -> str:
        remote = self.agents.get(agent_name)
        if remote is None:
            raise ValueError(f"Unknown remote agent: {agent_name}")

        try:
            base_url, card_path = _card_location(remote.card_url)
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(settings.a2a_timeout_seconds)
            ) as card_http:
                resolver = A2ACardResolver(
                    card_http,
                    base_url,
                    agent_card_path=card_path,
                )
                card = await resolver.get_agent_card()
        except Exception as exc:
            logger.warning("A2A Agent Card discovery failed for %s (%s)", agent_name, type(exc).__name__)
            raise A2ARemoteUnavailable(agent_name, "Agent Card discovery") from exc

        if card.name != remote.name:
            raise A2ARemoteUnavailable(agent_name, "Agent Card identity validation")
        interfaces = getattr(card, "supported_interfaces", [])
        if not any(item.protocol_binding == "JSONRPC" for item in interfaces):
            raise A2ARemoteUnavailable(agent_name, "JSON-RPC interface validation")

        rpc_http: httpx.AsyncClient | None = None
        client = None
        try:
            rpc_http = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.a2a_timeout_seconds)
            )
            client = ClientFactory(
                ClientConfig(
                    # message/send returns the complete Message or Task result;
                    # message/stream may expose intermediate ADK workflow
                    # artifacts before a final response is available.
                    streaming=False,
                    accepted_output_modes=["text/plain"],
                    httpx_client=rpc_http,
                )
            ).create(card)
            request = SendMessageRequest(
                message=Message(
                    message_id=uuid.uuid4().hex,
                    role="ROLE_USER",
                    parts=[Part(text=text)],
                ),
                configuration=SendMessageConfiguration(
                    accepted_output_modes=["text/plain"]
                ),
            )
            logger.info(
                "A2A JSON-RPC message started: agent=%s endpoint=%s",
                agent_name,
                interfaces[0].url,
            )
            events = [event async for event in client.send_message(request)]
            response_text = _extract_response(events, agent_name)
            logger.info("A2A JSON-RPC message completed: agent=%s", agent_name)
            return response_text
        except A2ARemoteUnavailable:
            raise
        except Exception as exc:
            logger.warning("A2A message exchange failed for %s (%s)", agent_name, type(exc).__name__)
            raise A2ARemoteUnavailable(agent_name, "message exchange") from exc
        finally:
            if client is not None:
                await client.close()
            elif rpc_http is not None:
                await rpc_http.aclose()
