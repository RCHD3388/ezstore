"""Load configuration without copying credentials into the agent project."""

import os
from pathlib import Path

from dotenv import load_dotenv

AGENT_DIR = Path(__file__).resolve().parents[1]
# Process environment wins, followed by local overrides and root .env.
load_dotenv(AGENT_DIR / ".env", override=False)
load_dotenv(AGENT_DIR.parent / ".env", override=False)

MODEL = os.getenv("AGENT_MODEL", "gemini-3.8-flash")
MCP_URL = os.getenv("MCP_URL", "http://localhost:8010/mcp")


def credentials_configured() -> bool:
    if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
        return bool(os.getenv("GOOGLE_CLOUD_PROJECT"))
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
