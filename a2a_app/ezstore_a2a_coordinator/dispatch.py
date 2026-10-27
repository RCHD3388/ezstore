"""Read-only routing and A2A delegation for coordinator workflow nodes."""

from __future__ import annotations

import asyncio

from ezstore_a2a_coordinator.a2a_transport import (
    A2ARemoteClient,
    A2ARemoteUnavailable,
)
from ezstore_a2a_coordinator.routing import (
    customer_subrequest,
    quotation_subrequest,
    resolve_route,
)

WRITE_REFUSAL = (
    "抱歉，EZStore A2A Coordinator 僅支援報價單查詢與客戶銷售洞察，"
    "不能新增、修改、刪除、複製或轉換任何業務資料。"
)
OFF_TOPIC_REFUSAL = (
    "抱歉，我只能協助查詢報價單，或透過客戶銷售洞察 Agent 查詢客戶概況、"
    "報價/訂單歷史、轉換分析與客戶比較。"
)


def _remote_error(error: A2ARemoteUnavailable) -> str:
    return (
        f"A2A 委派失敗：遠端 Agent `{error.agent_name}` 無法使用"
        f"（{error.phase}）。未改用 Backend、MCP 或其他直連方式，請稍後再試。"
    )


async def _send(
    remote_client: A2ARemoteClient,
    agent_name: str,
    request: str,
) -> str:
    try:
        return await remote_client.send_message(agent_name, request)
    except A2ARemoteUnavailable as error:
        raise error
    except Exception as exc:
        raise A2ARemoteUnavailable(agent_name, "message exchange") from exc


async def dispatch_request(
    message: str,
    predicted_route: str | None,
    remote_client: A2ARemoteClient | None = None,
) -> str:
    """Route supported reads and return verbatim specialist responses."""
    route = resolve_route(message, predicted_route)
    if route == "write_request":
        return WRITE_REFUSAL
    if route == "off_topic":
        return OFF_TOPIC_REFUSAL

    remote = remote_client or A2ARemoteClient()
    if route == "quotation_only":
        try:
            return await _send(
                remote, "quotation_agent", quotation_subrequest(message)
            )
        except A2ARemoteUnavailable as error:
            return _remote_error(error)

    if route == "customer_insight_only":
        try:
            return await _send(
                remote, "sales_insight_agent", message.strip()
            )
        except A2ARemoteUnavailable as error:
            return _remote_error(error)

    if route == "combined_cross_agent":
        requests = {
            "sales_insight_agent": customer_subrequest(message),
            "quotation_agent": quotation_subrequest(message),
        }
        names = list(requests)
        results = await asyncio.gather(
            *(_send(remote, name, requests[name]) for name in names),
            return_exceptions=True,
        )
        responses: dict[str, str] = {}
        failures: list[A2ARemoteUnavailable] = []
        for name, result in zip(names, results, strict=True):
            if isinstance(result, A2ARemoteUnavailable):
                failures.append(result)
            elif isinstance(result, Exception):
                failures.append(A2ARemoteUnavailable(name, "message exchange"))
            else:
                responses[name] = result

        if failures:
            sections = [
                f"{name} 回覆：\n{response}"
                for name, response in responses.items()
            ]
            sections.extend(_remote_error(error) for error in failures)
            return "\n\n".join(sections)

        return (
            "客戶銷售洞察（sales_insight_agent）：\n"
            f"{responses['sales_insight_agent']}\n\n"
            "報價單查詢（quotation_agent）：\n"
            f"{responses['quotation_agent']}"
        )

    # RouteName is exhaustive; this is defensive against invalid workflow state.
    return OFF_TOPIC_REFUSAL
