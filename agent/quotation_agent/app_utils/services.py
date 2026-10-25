"""Shared in-memory services for local ADK and scaffolded A2A endpoints."""

import functools

from google.adk.artifacts import InMemoryArtifactService
from google.adk.cli.service_registry import get_service_registry
from google.adk.sessions import InMemorySessionService

SESSION_SERVICE_URI = "shared://session"
ARTIFACT_SERVICE_URI = "shared://artifact"


@functools.cache
def get_session_service():
    return InMemorySessionService()


@functools.cache
def get_artifact_service():
    return InMemoryArtifactService()


_registry = get_service_registry()
_registry.register_session_service("shared", lambda uri, **kw: get_session_service())
_registry.register_artifact_service("shared", lambda uri, **kw: get_artifact_service())
