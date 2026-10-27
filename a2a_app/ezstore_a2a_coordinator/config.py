"""Runtime configuration for the coordinator and remote A2A endpoints."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass(frozen=True)
class Settings:
    agent_model: str = os.getenv("AGENT_MODEL", "gemini-3.8-flash")
    quotation_agent_card_url: str = os.getenv(
        "QUOTATION_AGENT_CARD_URL",
        "http://localhost:8011/a2a/quotation_agent/.well-known/agent-card.json",
    )
    sales_insight_agent_card_url: str = os.getenv(
        "SALES_INSIGHT_AGENT_CARD_URL",
        "http://localhost:8012/.well-known/agent-card.json",
    )
    a2a_timeout_seconds: float = float(os.getenv("A2A_TIMEOUT_SECONDS", "180"))


settings = Settings()
