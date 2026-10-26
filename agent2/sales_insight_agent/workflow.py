"""Explicit ADK graph for read-only customer sales insights."""

from __future__ import annotations

import os
import re
from typing import Any

from google.adk import Event
from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.workflow import Workflow

from sales_insight_agent.backend_client import BackendAPIError, ReadOnlyBackendClient
from sales_insight_agent.intent import SalesInsightIntent
from sales_insight_agent.operations import (
    CustomerAmbiguous,
    CustomerNotFound,
    compare_customers,
    conversion_analysis,
    customer_overview,
    order_history,
    quotation_history,
)


MODEL = os.getenv("AGENT_MODEL", "gemini-3.8-flash")
_WRITE_VERBS = re.compile(
    r"(?:修改|新增|建立|創建|刪除|移除|更新|編輯|發佈|發布|複製|create|update|delete|remove|edit|publish|duplicate)",
    re.IGNORECASE,
)
_DATA_ENTITIES = re.compile(
    r"(?:客戶|客戶資料|customer|產品|product|報價|報價單|quotation|訂單|order)",
    re.IGNORECASE,
)
_CONVERT_REQUEST = re.compile(r"(?:將|把).{0,40}(?:轉成|轉換為|建立為).{0,12}訂單")
_COMMAND_WORDS = re.compile(
    r"(?:查詢|查看|列出|分析|比較|請|幫我|customer|quotation|order|history|overview|compare|analy[sz]e)",
    re.IGNORECASE,
)

_ACTIONS = {
    "customer_overview",
    "quotation_history",
    "order_history",
    "conversion_analysis",
    "compare_customers",
}

_INSTRUCTION = """你是 Sales & Customer Insight Agent 的意圖分類節點。只輸出符合 schema 的結構化意圖，不要回答使用者，也不要呼叫工具。
可用 action 僅有 customer_overview、quotation_history、order_history、conversion_analysis、compare_customers、write_request、off_topic。
只把查詢客戶銷售概況、列出該客戶報價歷史、列出訂單歷史、分析報價是否關聯訂單、比較兩個客戶歸類為前五項。
任何要求新增、修改、刪除、發佈、複製、建立訂單或執行報價單管理 Agent 操作的要求歸類 write_request。其他非上述功能歸類 off_topic。
將訊息內客戶名稱按提及順序填入 customer_names。只可抽取名稱，不可推測或產生任何業務數字。
輸入會包含目前訊息及可能存在的待補資料。若上一個意圖待補客戶名稱，而目前訊息只提供名稱，請保留原 action 並抽取補充的客戶名稱。"""


classifier = LlmAgent(
    name="classify_intent",
    model=MODEL,
    instruction=_INSTRUCTION,
    output_schema=SalesInsightIntent,
    output_key="intent",
)


def _text_from_input(node_input: Any) -> str:
    if isinstance(node_input, str):
        return node_input
    text = getattr(node_input, "text", None)
    if text:
        return str(text)
    parts = getattr(node_input, "parts", None) or []
    return "".join(str(part.text) for part in parts if getattr(part, "text", None))


def load_context(ctx: Context, node_input: Any) -> Event:
    message = _text_from_input(node_input).strip()
    pending = ctx.state.get("pending_intent")
    context_text = f"目前使用者訊息：\n{message}"
    if pending:
        context_text += f"\n\n前一輪等待補充的意圖（必須優先承接）：\n{pending}"
    return Event(
        output=context_text,
        state={"current_message": message},
    )


def is_write_request(message: str) -> bool:
    """Programmatic write guard, independent of the LLM classification."""
    return bool((_WRITE_VERBS.search(message) and _DATA_ENTITIES.search(message)) or _CONVERT_REQUEST.search(message))


def _intent_from_state(value: Any) -> SalesInsightIntent:
    if isinstance(value, SalesInsightIntent):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, str):
        return SalesInsightIntent.model_validate_json(value)
    return SalesInsightIntent.model_validate(value or {})


def resolve_route(
    message: str,
    intent_value: Any,
    pending: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    """Apply write guard, pending-turn continuation, and required-name checks."""
    if is_write_request(message):
        return "reject_write_request", pending, None

    intent = _intent_from_state(intent_value)
    if intent.action == "write_request":
        return "reject_write_request", pending, None

    if pending and not _COMMAND_WORDS.search(message):
        action = str(pending.get("action", ""))
        if action in _ACTIONS:
            names = list(intent.customer_names)
            previous = list(pending.get("customer_names", []))
            if action == "compare_customers" and len(names) < 2:
                names = previous + [name for name in names if name not in previous]
            elif not names:
                names = [message] if message else previous
            intent = SalesInsightIntent(action=action, customer_names=names)

    if intent.action not in _ACTIONS:
        return "off_topic", pending, None
    needed = 2 if intent.action == "compare_customers" else 1
    if len(intent.customer_names) < needed:
        next_pending = {
            "action": intent.action,
            "customer_names": intent.customer_names,
        }
        return "clarify", next_pending, None
    return intent.action, None, intent.model_dump()


def route(ctx: Context) -> Event:
    action, pending, resolved = resolve_route(
        str(ctx.state.get("current_message", "")),
        ctx.state.get("intent"),
        ctx.state.get("pending_intent"),
    )
    update: dict[str, Any] = {"resolved_intent": resolved}
    if action == "clarify":
        update["pending_intent"] = pending
    elif action in _ACTIONS:
        update["pending_intent"] = None
    return Event(route=action, state=update)


def _set_result(ctx: Context, text: str) -> Event:
    return Event(output=text, state={"result": text})


def _customer_names(ctx: Context) -> list[str]:
    intent = _intent_from_state(ctx.state.get("resolved_intent"))
    return intent.customer_names


def _run_customer_operation(ctx: Context, function: Any, *names: str) -> Event:
    try:
        return _set_result(ctx, function(ReadOnlyBackendClient(), *names))
    except CustomerNotFound as exc:
        return _set_result(ctx, f"找不到客戶「{exc}」，請確認客戶名稱後再試一次。")
    except CustomerAmbiguous as exc:
        choices = "、".join(str(row.get("name", "名稱未提供")) for row in exc.customers)
        return _set_result(ctx, f"找到多位符合的客戶，請確認要查詢哪一位：{choices}")
    except BackendAPIError as exc:
        return _set_result(ctx, f"目前無法讀取 Backend 資料：{exc}")
    except (KeyError, TypeError, ValueError) as exc:
        return _set_result(ctx, f"Backend 回傳資料無法完成分析：{exc}")


def customer_overview_node(ctx: Context) -> Event:
    return _run_customer_operation(ctx, customer_overview, _customer_names(ctx)[0])


def quotation_history_node(ctx: Context) -> Event:
    return _run_customer_operation(ctx, quotation_history, _customer_names(ctx)[0])


def order_history_node(ctx: Context) -> Event:
    return _run_customer_operation(ctx, order_history, _customer_names(ctx)[0])


def conversion_analysis_node(ctx: Context) -> Event:
    return _run_customer_operation(ctx, conversion_analysis, _customer_names(ctx)[0])


def compare_customers_node(ctx: Context) -> Event:
    return _run_customer_operation(ctx, compare_customers, *_customer_names(ctx)[:2])


def clarify(ctx: Context) -> Event:
    pending = ctx.state.get("pending_intent") or {}
    action = pending.get("action")
    names = pending.get("customer_names", [])
    if action == "compare_customers" and len(names) == 1:
        text = f"請再提供要比較的另一位客戶名稱（目前已收到：{names[0]}）。"
    elif action == "compare_customers":
        text = "請提供要比較的兩位客戶名稱。"
    else:
        text = "請提供要查詢的客戶名稱。"
    return _set_result(ctx, text)


def reject_write_request(ctx: Context) -> Event:
    return _set_result(
        ctx,
        "抱歉，我是 Sales & Customer Insight Agent，只能提供客戶銷售概況、報價歷史、訂單歷史、報價轉訂單分析與客戶比較等五項唯讀功能，不能新增、修改、刪除或建立資料。",
    )


def off_topic(ctx: Context) -> Event:
    return _set_result(
        ctx,
        "抱歉，我是 Sales & Customer Insight Agent，只能提供客戶銷售概況、報價歷史、訂單歷史、報價轉訂單分析與客戶比較等五項唯讀功能。",
    )


def respond(ctx: Context) -> str:
    return str(ctx.state.get("result", "目前無法產生分析結果。"))


root_agent = Workflow(
    name="sales_insight_agent",
    description="Read-only customer sales insights grounded in the EZStore Backend API.",
    edges=[
        ("START", load_context),
        (load_context, classifier),
        (classifier, route),
        (
            route,
            {
                "customer_overview": customer_overview_node,
                "quotation_history": quotation_history_node,
                "order_history": order_history_node,
                "conversion_analysis": conversion_analysis_node,
                "compare_customers": compare_customers_node,
                "clarify": clarify,
                "reject_write_request": reject_write_request,
                "off_topic": off_topic,
            },
        ),
        (customer_overview_node, respond),
        (quotation_history_node, respond),
        (order_history_node, respond),
        (conversion_analysis_node, respond),
        (compare_customers_node, respond),
        (clarify, respond),
        (reject_write_request, respond),
        (off_topic, respond),
    ],
)
