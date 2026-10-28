"""The dashboard reads saved results and never converts failures into passes."""

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ezstore_a2a_coordinator.customer_overview_dashboard import create_server, load_view


def _report(path, checks):
    path.write_text(json.dumps({
        "checks": checks,
        "sales_agent_card": {"name": "sales_insight_agent", "skills": [{"id": "customer_overview"}]},
        "sales_a2a_tasks": [{"id": "task-1", "status": {"state": "TASK_STATE_COMPLETED"}}],
        "sales_remote_result": "recorded text",
    }), encoding="utf-8")


def test_view_uses_saved_check_values_and_task(tmp_path):
    path = tmp_path / "report.json"
    _report(path, {"card": True, "exchange": False})
    view = load_view(path)
    assert view["passed"] is False
    assert view["checks"]["exchange"] is False
    assert view["a2a_tasks"][0]["id"] == "task-1"
    assert view["remote_result"] == "recorded text"
    _report(path, {"card": True, "exchange": True})
    assert load_view(path)["passed"] is True


def test_dashboard_get_and_write_refusal(tmp_path):
    path = tmp_path / "report.json"
    _report(path, {"card": True, "exchange": False})
    server = create_server(path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(base + "/api/report") as response:
            payload = json.load(response)
        assert payload["passed"] is False
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                urlopen(Request(base + "/api/report", data=b"{}", method=method))
                assert False, f"{method} unexpectedly accepted"
            except HTTPError as exc:
                assert exc.code == 405
        assert load_view(path)["checks"]["exchange"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
