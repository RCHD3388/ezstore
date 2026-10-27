import http.client
import json
import threading

import pytest

from okf_knowledge.verification_dashboard import create_server, load_report


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"passed": True, "checks": [
        {"id": "fixture", "label": "Fixture failure", "passed": False, "detail": {}}
    ]}), encoding="utf-8")
    return path


@pytest.fixture
def dashboard(report):
    server = create_server(report, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def request(port, method, path):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path)
    response = connection.getresponse()
    status, data = response.status, response.read()
    connection.close()
    return status, data


def test_saved_failure_is_preserved_and_overall_is_derived(report):
    before = report.read_bytes()
    result = load_report(report)
    assert not result["passed"] and not result["checks"][0]["passed"]
    assert report.read_bytes() == before


def test_dashboard_api_returns_saved_failure(dashboard):
    status, data = request(dashboard, "GET", "/api/report")
    assert status == 200 and json.loads(data)["passed"] is False


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_dashboard_rejects_write_methods(dashboard, method):
    assert request(dashboard, method, "/api/report")[0] == 405


def test_missing_evidence_returns_unavailable_not_pass(report, dashboard):
    report.unlink()
    status, data = request(dashboard, "GET", "/api/report")
    assert status == 503 and "error" in json.loads(data)
    assert request(dashboard, "GET", "/../../.env")[0] == 404
