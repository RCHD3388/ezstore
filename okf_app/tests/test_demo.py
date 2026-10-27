import http.client
import json
import threading
from urllib.parse import urlencode

import pytest

from okf_knowledge.demo import create_server, render_markdown


@pytest.fixture
def demo():
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def request(port, path, method="GET"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path)
    response = connection.getresponse()
    status, body = response.status, response.read()
    connection.close()
    return status, body


def test_demo_uses_the_consumer_and_displays_source(demo):
    question = "What is the default pricing factor for a VIP customer?"
    status, body = request(demo, "/api/ask?" + urlencode({"question": question}))
    answer = json.loads(body)
    assert status == 200 and answer["question"] == question
    assert answer["supported"] and "0.80" in answer["answer_html"]
    assert answer["document"] == "quotation-pricing.md"
    assert "<table>" in answer["answer_html"]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_demo_rejects_all_write_methods(demo, method):
    status, _ = request(demo, "/api/ask?question=anything", method)
    assert status == 405


def test_source_endpoint_only_serves_approved_concepts(demo):
    status, body = request(demo, "/api/document?name=quotation-lifecycle.md")
    assert status == 200 and "published" in json.loads(body)["body"]
    assert request(demo, "/api/document?name=../../.env")[0] == 404
    assert request(demo, "/../../.env")[0] == 404


def test_concept_list_and_input_validation(demo):
    status, body = request(demo, "/api/concepts")
    assert status == 200 and len(json.loads(body)) == 4
    assert request(demo, "/api/ask?question=")[0] == 400


def test_html_is_escaped_and_tables_rendered():
    assert "<script>" not in render_markdown("<script>alert(1)</script>")
    assert "<table>" in render_markdown("| A | B |\n|---|---|\n| a | b |")
