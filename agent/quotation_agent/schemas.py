"""Structured classifier output, validated before any tool is called."""

from typing import Literal

from pydantic import BaseModel, Field


class QuotationIntent(BaseModel):
    intent: Literal[
        "get_quotation", "list_customer_quotations", "duplicate_quotation",
        "update_pricing_factor", "adjust_total_price", "convert_to_order",
        "provide_details", "off_topic", "service_error",
    ]
    quotation_number: str | None = Field(default=None, description="使用者提供的報價單編號；未提供為 null")
    customer_name: str | None = Field(default=None, description="查詢報價單清單的客戶名稱；未提供為 null")
    new_pricing_factor: float | None = Field(default=None, description="新的報價因子；未提供為 null")
    target_total_price: float | None = Field(default=None, description="目標總價；未提供為 null")
    error_reason: Literal["missing_credentials", "model_unavailable", "authentication_failed", "model_not_found", "quota_exceeded", "model_busy"] | None = None
