"""ADK graph: deterministic guarded routing and A2A delegation."""

from __future__ import annotations

from typing import Any

from google.adk.agents.context import Context
from google.adk.events import Event
from google.adk.workflow import Workflow
from google.genai import types

from ezstore_a2a_coordinator.dispatch import dispatch_request
from ezstore_a2a_coordinator.intent import RouteName
from ezstore_a2a_coordinator.routing import resolve_route


def _input_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    text = getattr(value, "text", None)
    if text:
        return str(text).strip()
    parts = getattr(value, "parts", None) or []
    return "".join(
        str(part.text)
        for part in parts
        if getattr(part, "text", None)
    ).strip()


def load_request(ctx: Context, node_input: Any) -> Event:
    message = _input_text(node_input)
    return Event(output=message, state={"user_request": message})


def route_request(ctx: Context) -> Event:
    route: RouteName = resolve_route(
        str(ctx.state.get("user_request", "")), None
    )
    return Event(output=route, route=route, state={"resolved_route": route})


async def _handle(ctx: Context, route: RouteName) -> str:
    return await dispatch_request(
        str(ctx.state.get("user_request", "")),
        route,
    )


async def quotation_only(ctx: Context) -> str:
    return await _handle(ctx, "quotation_only")


async def customer_insight_only(ctx: Context) -> str:
    return await _handle(ctx, "customer_insight_only")


async def combined_cross_agent(ctx: Context) -> str:
    return await _handle(ctx, "combined_cross_agent")


def reject_write_request(ctx: Context) -> str:
    return dispatch_request_sync_refusal("write_request")


def off_topic(ctx: Context) -> str:
    return dispatch_request_sync_refusal("off_topic")


def dispatch_request_sync_refusal(route: str) -> str:
    from ezstore_a2a_coordinator.dispatch import OFF_TOPIC_REFUSAL, WRITE_REFUSAL

    return WRITE_REFUSAL if route == "write_request" else OFF_TOPIC_REFUSAL


def respond(node_input: str) -> Event:
    return Event(
        output=node_input,
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=node_input)],
        ),
    )


def build_workflow() -> Workflow:
    branches = {
        "quotation_only": quotation_only,
        "customer_insight_only": customer_insight_only,
        "combined_cross_agent": combined_cross_agent,
        "write_request": reject_write_request,
        "off_topic": off_topic,
    }
    return Workflow(
        name="ezstore_a2a_coordinator",
        description=(
            "Read-only coordinator that delegates quotation and customer insight "
            "requests to independent specialists through the A2A protocol."
        ),
        edges=[
            ("START", load_request),
            (load_request, route_request),
            (route_request, branches),
            *[(handler, respond) for handler in branches.values()],
        ],
    )
