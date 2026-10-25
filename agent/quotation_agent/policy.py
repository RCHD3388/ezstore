"""Deterministic domain checks, required fields, and tool argument allowlists."""

import math
import re

from .schemas import QuotationIntent

PENDING_KEY = "pending_quotation_request"
REQUIRED_FIELDS = {
    "get_quotation": ("quotation_number",),
    "list_customer_quotations": ("customer_name",),
    "duplicate_quotation": ("quotation_number",),
    "update_pricing_factor": ("quotation_number", "new_pricing_factor"),
    "adjust_total_price": ("quotation_number", "target_total_price"),
    "convert_to_order": ("quotation_number",),
}
FIELD_LABELS = {
    "quotation_number": "報價單編號",
    "customer_name": "客戶名稱",
    "new_pricing_factor": "新的報價因子（大於 0 的數值）",
    "target_total_price": "目標總價（大於 0 的數值）",
}
REFUSAL = "抱歉，我只能處理報價單相關操作：查詢報價單、查詢客戶報價單清單、複製報價單、修改報價因子或總價，以及報價單轉訂單。無法處理天氣、閒聊或客戶、產品的新增修改等需求。"

_UNRELATED = re.compile(
    r"天氣|天气|氣溫|气温|weather|forecast|聊聊天|講笑話|讲笑话|tell\s+(?:me\s+)?a\s+joke|"
    r"(?:新增|新建|建立|刪除|删除|修改|更新|更改|編輯|编辑)\s*(?:一[個筆家]?\s*)?(?:客戶|客户|產品|产品)(?!的?報價|的?报价)|"
    r"(?:客戶|客户|產品|产品)(?:資料|资料|名稱|名称|地址|電話|电话|單價|单价).{0,12}(?:改為|改成|修改|更新)|"
    r"(?:create|add|delete|remove|update|edit)\s+(?:(?:a|an|the)\s+)?(?:customer|product)\b",
    re.IGNORECASE,
)
_QUOTATION_CONTEXT = re.compile(r"報價|报价|quotation|\bquote\b|\bQT-", re.IGNORECASE)


def user_text(ctx) -> str:
    content = ctx.user_content
    return "".join(part.text or "" for part in (content.parts or [])) if content else ""


def clarification_history(ctx) -> dict | None:
    """Recover conversational context when a restored session has no state.

    ADK permits ordinary history events, but rejects client-supplied state
    actions. Only the most recent unresolved clarification supplies context;
    the LLM still classifies the operation and the router validates its fields.
    """
    events = getattr(getattr(ctx, "session", None), "events", [])
    clarification = None
    for event in reversed(events):
        content = event.content
        text = "".join(part.text or "" for part in (content.parts or [])) if content else ""
        if not text:
            continue
        if clarification is None:
            if event.author == "user":
                continue
            if not (text.startswith("請提供") and "接續完成這項報價單操作" in text):
                return None
            clarification = text
        elif event.author == "user":
            if in_domain(text, False):
                return {"request": text, "clarification": clarification}
            return None
    return None


def forbidden_request(text: str) -> bool:
    return bool(_UNRELATED.search(text))


def in_domain(text: str, has_pending: bool) -> bool:
    return not forbidden_request(text) and (bool(_QUOTATION_CONTEXT.search(text)) or has_pending)


def merge_pending(intent: QuotationIntent, pending: dict | None) -> QuotationIntent:
    if pending and intent.intent in (pending["intent"], "provide_details"):
        values = {**pending, **intent.model_dump(exclude_none=True, exclude={"intent"})}
        return QuotationIntent.model_validate(values)
    return intent


def missing_fields(intent: QuotationIntent) -> list[str]:
    missing = []
    for field in REQUIRED_FIELDS[intent.intent]:
        value = getattr(intent, field)
        if isinstance(value, str):
            value = value.strip()
            setattr(intent, field, value or None)
        if value is None or value == "":
            missing.append(field)
        elif field in ("new_pricing_factor", "target_total_price") and (
            not math.isfinite(value) or value <= 0
        ):
            setattr(intent, field, None)
            missing.append(field)
    return missing


def tool_arguments(intent: QuotationIntent) -> dict:
    return {field: getattr(intent, field) for field in REQUIRED_FIELDS[intent.intent]}
