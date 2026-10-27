"""Programmatic safety checks and deterministic route validation."""

from __future__ import annotations

import re

from ezstore_a2a_coordinator.intent import RouteName

_QUOTATION_ID = re.compile(r"\bQT-\d{8}-\d{3}\b", re.IGNORECASE)
_BUSINESS_ENTITY = re.compile(
    r"(?:quotation|quote|customer|order|product|報價單?|客戶|訂單|產品)",
    re.IGNORECASE,
)
_WRITE_ACTION = re.compile(
    r"(?:\b(?:create|modify|update|edit|delete|remove|duplicate|copy|publish|convert)\b"
    r"|新增|修改|更新|編輯|刪除|移除|複製|建立訂單|建立報價|轉成訂單|轉為訂單|轉換為訂單|轉單|發佈|發布)",
    re.IGNORECASE,
)
_INSIGHT_ACTION = re.compile(
    r"(?:overview|insight|analy[sz]e|analysis|history|compare|comparison|sales|list"
    r"|概況|分析|歷史|比較|銷售|列出)",
    re.IGNORECASE,
)
_LOOKUP_ACTION = re.compile(
    r"(?:show|display|find|get|look\s*up|check|query|查詢|查看|顯示|列出)",
    re.IGNORECASE,
)


def is_write_request(message: str) -> bool:
    """Refuse business-data mutations regardless of the classifier output."""
    return bool(_BUSINESS_ENTITY.search(message) and _WRITE_ACTION.search(message))


def resolve_route(message: str, predicted_route: str | None) -> RouteName:
    """Apply deterministic allow-listing and write guards to the model label."""
    if is_write_request(message) or predicted_route == "write_request":
        return "write_request"

    quotation_id_present = bool(_QUOTATION_ID.search(message))
    insight_request = bool(_INSIGHT_ACTION.search(message))
    mentions_customer = bool(re.search(r"(?:customer|客戶)", message, re.IGNORECASE))
    mentions_quotation = bool(re.search(r"(?:quotation|quote|報價單?)", message, re.IGNORECASE))

    if quotation_id_present and insight_request and mentions_customer:
        return "combined_cross_agent"

    if quotation_id_present and (
        mentions_quotation or _LOOKUP_ACTION.search(message)
    ):
        return "quotation_only"

    if mentions_customer and insight_request:
        return "customer_insight_only"

    # A classifier cannot expand the supported surface beyond these explicit cues.
    if predicted_route in {"quotation_only", "combined_cross_agent"} and quotation_id_present:
        return predicted_route  # type: ignore[return-value]
    if predicted_route == "customer_insight_only" and mentions_customer and insight_request:
        return "customer_insight_only"
    return "off_topic"


def quotation_subrequest(message: str) -> str:
    match = _QUOTATION_ID.search(message)
    if not match:
        raise ValueError("A quotation number is required for quotation delegation.")
    return f"我要查詢報價單，報價單編號：{match.group(0).upper()}"


def customer_subrequest(message: str) -> str:
    """Remove the quotation-only clause from a combined prompt for the insight agent."""
    text = _QUOTATION_ID.sub("", message)
    text = re.sub(
        r"(?is)(?:\s*(?:and\s+also|and|also)?\s*(?:show|display|find|get|look\s*up|check)?\s*(?:me\s+)?(?:the\s+)?(?:quotation|quote)(?:\s+number)?\s*[,.:：]*)\s*$",
        "",
        text,
    )
    text = re.sub(
        r"(?is)(?:\s*(?:並且|並|同時|也)?\s*(?:查詢|查看|顯示|列出)?\s*報價單?\s*[,.:：]*)\s*$",
        "",
        text,
    )
    text = re.sub(r"\s*(?:and|also|並且|並|同時|也)\s*[,.:：]*\s*$", "", text)
    return text.strip(" \t\r\n,.;:：，。") or message
