"""Structured intent returned by the workflow's only LLM node."""

from typing import Literal

from pydantic import BaseModel, Field


Action = Literal[
    "customer_overview",
    "quotation_history",
    "order_history",
    "conversion_analysis",
    "compare_customers",
    "write_request",
    "off_topic",
]


class SalesInsightIntent(BaseModel):
    action: Action = Field(description="One supported insight action or a refusal route.")
    customer_names: list[str] = Field(
        default_factory=list,
        description="Customer names mentioned, in order of appearance.",
    )
    reason: str = Field(default="", description="Short reason for the classification.")
