"""Structured output used only to classify coordinator requests."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RouteName = Literal[
    "quotation_only",
    "customer_insight_only",
    "combined_cross_agent",
    "write_request",
    "off_topic",
]


class CoordinatorIntent(BaseModel):
    """A route label; business facts and remote results never come from this model."""

    route: RouteName = Field(description="One of the supported coordinator routes.")
