"""Exercise actual Coordinator transport failure paths with HTTP interception."""

import json

import httpx
import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentInterface
from google.protobuf.json_format import MessageToDict

from ezstore_a2a_coordinator import a2a_transport
from ezstore_a2a_coordinator.dispatch import dispatch_request


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase", ["Agent Card discovery", "message exchange"])
async def test_quotation_a2a_failure_never_contacts_backend_or_mcp(monkeypatch, failure_phase):
    card_url = "https://quotation.example/.well-known/agent-card.json"
    rpc_url = "https://quotation.example/a2a/quotation_agent"
    calls = []
    card = AgentCard(
        name="quotation_agent",
        description="Read-only quotation specialist",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(url=rpc_url, protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )

    def handle(request):
        calls.append((request.method, str(request.url)))
        if request.method == "GET" and str(request.url) == card_url:
            if failure_phase == "Agent Card discovery":
                return httpx.Response(503, json={"error": "unavailable"})
            return httpx.Response(200, json=MessageToDict(card))
        if request.method == "POST" and str(request.url) == rpc_url:
            body = json.loads(request.content)
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body["id"],
                "error": {"code": -32603, "message": "Quotation specialist unavailable"},
            })
        pytest.fail(f"Unexpected outbound request: {request.method} {request.url}")

    real_client = httpx.AsyncClient

    def intercepted_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handle)
        kwargs["trust_env"] = False
        return real_client(*args, **kwargs)

    monkeypatch.setattr(a2a_transport.httpx, "AsyncClient", intercepted_client)
    remote = a2a_transport.A2ARemoteClient({
        "quotation_agent": a2a_transport.RemoteAgent("quotation_agent", card_url)
    })
    result = await dispatch_request(
        "Show me quotation QT-20260330-001.", "quotation_only", remote
    )
    assert "quotation_agent" in result
    assert failure_phase in result
    assert calls == (
        [("GET", card_url)] if failure_phase == "Agent Card discovery"
        else [("GET", card_url), ("POST", rpc_url)]
    )
