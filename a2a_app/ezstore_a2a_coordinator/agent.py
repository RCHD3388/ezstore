"""EZStore A2A Coordinator with deterministic routing and A2A delegation."""

from google.adk.apps import App

from ezstore_a2a_coordinator.workflow import build_workflow

root_agent = build_workflow()
app = App(name="ezstore_a2a_coordinator", root_agent=root_agent)

__all__ = ["app", "root_agent"]
