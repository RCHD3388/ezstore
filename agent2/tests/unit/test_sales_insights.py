from __future__ import annotations

from typing import Any

import pytest

from sales_insight_agent.backend_client import ReadOnlyBackendClient
from sales_insight_agent.intent import SalesInsightIntent
from sales_insight_agent.operations import (
    compare_customers,
    conversion_analysis,
    customer_overview,
    order_history,
    quotation_history,
)
from sales_insight_agent.workflow import is_write_request, resolve_route


class FakeBackend:
    def __init__(self) -> None:
        self.customers = {
            "史塔克工業": {
                "id": 1,
                "name": "史塔克工業股份有限公司",
                "level": "vip",
                "credit_score": 95,
            },
            "膠囊公司": {
                "id": 2,
                "name": "膠囊公司",
                "level": "vip",
                "credit_score": 88,
            },
        }
        self.quotations = {
            1: [
                {"id": 10, "quotation_number": "QT-1", "status": "published", "total_price": "100.5", "created_at": "2026-01-15T02:00:00Z"},
                {"id": 11, "quotation_number": "QT-2", "status": "draft", "total_price": "200", "created_at": "2026-02-15T02:00:00Z"},
            ],
            2: [
                {"id": 12, "quotation_number": "QT-3", "status": "published", "total_price": "50", "created_at": "2026-03-15T02:00:00Z"},
            ],
        }
        self.orders = {
            1: [
                {"id": 20, "order_number": "ORD-1", "status": "completed", "total_price": "90", "created_at": "2026-01-18T01:00:00Z", "quotation_id": 10},
                {"id": 21, "order_number": "ORD-2", "status": "pending", "total_price": "50", "created_at": "2026-02-18T01:00:00Z", "quotation_id": None},
            ],
            2: [
                {"id": 22, "order_number": "ORD-3", "status": "pending", "total_price": "49", "created_at": "2026-03-18T01:00:00Z", "quotation_id": 12},
                {"id": 23, "order_number": "ORD-4", "status": "completed", "total_price": "6", "created_at": "2026-04-18T01:00:00Z", "quotation_id": None},
            ],
        }

    def search_customers(self, name: str) -> list[dict[str, Any]]:
        return [value for key, value in self.customers.items() if key in name or name in key]

    def get_customer(self, customer_id: int) -> dict[str, Any]:
        return next(value for value in self.customers.values() if value["id"] == customer_id)

    def list_quotations(self, customer_id: int) -> list[dict[str, Any]]:
        return self.quotations[customer_id]

    def list_orders(self, customer_id: int) -> list[dict[str, Any]]:
        return self.orders[customer_id]

    def get_quotation(self, quotation_id: int) -> dict[str, Any]:
        return next(row for values in self.quotations.values() for row in values if row["id"] == quotation_id)


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


def test_customer_overview_uses_backend_values(backend: FakeBackend) -> None:
    result = customer_overview(backend, "史塔克工業")
    assert "史塔克工業股份有限公司" in result
    assert "客戶等級：vip" in result
    assert "信用評分：95" in result
    assert "報價單數量：2" in result
    assert "訂單數量：2" in result
    assert "報價總額：300.5" in result
    assert "訂單總額：140" in result
    assert "completed 1 筆、pending 1 筆" in result


def test_quotation_history_has_required_fields(backend: FakeBackend) -> None:
    result = quotation_history(backend, "史塔克工業")
    assert "QT-1" in result and "published" in result and "100.5" in result
    assert "2026-01-15" in result
    assert "QT-2" in result and "draft" in result and "2026-02-15" in result


def test_order_history_identifies_link_and_standalone(backend: FakeBackend) -> None:
    result = order_history(backend, "史塔克工業")
    assert "ORD-1" in result and "completed" in result and "90" in result
    assert "關聯報價單：QT-1" in result
    assert "ORD-2" in result and "獨立訂單（沒有關聯報價單）" in result


def test_conversion_analysis_uses_linked_quotation_ids(backend: FakeBackend) -> None:
    result = conversion_analysis(backend, "史塔克工業")
    assert "已轉換 1 / 2 張報價單" in result
    assert "已關聯訂單：\n- QT-1" in result
    assert "尚未關聯訂單：\n- QT-2" in result


def test_compare_customers_reports_sales_metrics(backend: FakeBackend) -> None:
    result = compare_customers(backend, "史塔克工業", "膠囊公司")
    assert "史塔克工業股份有限公司" in result and "信用評分：95" in result
    assert "報價單數量：2；報價總額：300.5" in result
    assert "訂單數量：2；訂單總額：140" in result
    assert "膠囊公司" in result and "信用評分：88" in result
    assert "已關聯轉換報價單數：1" in result


def test_off_topic_weather_routes_to_refusal() -> None:
    route, _, _ = resolve_route(
        "今天天氣如何？",
        SalesInsightIntent(action="off_topic"),
    )
    assert route == "off_topic"


def test_write_request_is_programmatically_rejected_without_http_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[str] = []
    monkeypatch.setattr("sales_insight_agent.backend_client.urlopen", lambda req, **kwargs: requests.append(req.get_method()))
    message = "請修改史塔克工業的報價單"
    assert is_write_request(message)
    route, _, _ = resolve_route(message, SalesInsightIntent(action="customer_overview", customer_names=["史塔克工業"]))
    assert route == "reject_write_request"
    assert requests == []
    assert not hasattr(ReadOnlyBackendClient, "post")
    assert not hasattr(ReadOnlyBackendClient, "put")
    assert not hasattr(ReadOnlyBackendClient, "patch")
    assert not hasattr(ReadOnlyBackendClient, "delete")


def test_clarify_then_complete_resumes_pending_action() -> None:
    first_route, pending, _ = resolve_route(
        "幫我查看客戶銷售概況",
        SalesInsightIntent(action="customer_overview"),
    )
    assert first_route == "clarify"
    assert pending == {"action": "customer_overview", "customer_names": []}

    next_route, next_pending, intent = resolve_route(
        "史塔克工業",
        SalesInsightIntent(action="off_topic"),
        pending,
    )
    assert next_route == "customer_overview"
    assert next_pending is None
    assert intent == {
        "action": "customer_overview",
        "customer_names": ["史塔克工業"],
        "reason": "",
    }


def test_pagination_reads_until_backend_total_is_collected() -> None:
    client = ReadOnlyBackendClient(base_url="http://example.test/api/v1")
    calls: list[int] = []

    def fake_get_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(params["page"])
        if params["page"] == 1:
            return {"data": [{"id": 1}, {"id": 2}], "page": 1, "page_size": 2, "total": 3}
        return {"data": [{"id": 3}], "page": 2, "page_size": 2, "total": 3}

    client._get_json = fake_get_json  # type: ignore[method-assign]
    assert [row["id"] for row in client._get_all("/customers")] == [1, 2, 3]
    assert calls == [1, 2]
