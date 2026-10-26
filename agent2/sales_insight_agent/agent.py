"""ADK application entry point for Sales & Customer Insight Agent."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()
if os.getenv("GEMINI_API_KEY"):
    os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "FALSE"
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
else:
    os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "FALSE")

from google.adk.apps import App  # noqa: E402

from sales_insight_agent.workflow import MODEL, root_agent

app = App(name="sales_insight_agent", root_agent=root_agent)

__all__ = ["app", "root_agent", "MODEL"]
