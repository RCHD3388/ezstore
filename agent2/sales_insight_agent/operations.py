"""Deterministic sales insight calculations over Backend API responses."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol


class ReadOnlyClient(Protocol):
    def search_customers(self, name: str) -> list[dict[str, Any]]: ...
    def get_customer(self, customer_id: int) -> dict[str, Any]: ...
    def list_quotations(self, customer_id: int) -> list[dict[str, Any]]: ...
    def list_orders(self, customer_id: int) -> list[dict[str, Any]]: ...
    def get_quotation(self, quotation_id: int) -> dict[str, Any]: ...


def money(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def display_number(value: Decimal) -> str:
    normalized = value.normalize()
    return f"{normalized:,.2f}".rstrip("0").rstrip(".") if normalized else "0"


def display_date(value: Any) -> str:
    if not value:
        return "日期未提供"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return str(value)


class CustomerNotFound(Exception):
    pass


class CustomerAmbiguous(Exception):
    def __init__(self, customers: list[dict[str, Any]]):
        self.customers = customers
        super().__init__("Multiple matching customers")


def resolve_customer(client: ReadOnlyClient, requested_name: str) -> dict[str, Any]:
    rows = client.search_customers(requested_name)
    needle = requested_name.casefold().strip()
    reasonable = [
        row for row in rows
        if needle in str(row.get("name", "")).casefold()
        or str(row.get("name", "")).casefold() in needle
    ]
    # An API search may already return one fuzzy but reasonable result.
    if not reasonable and len(rows) == 1:
        reasonable = rows
    unique = {int(row["id"]): row for row in reasonable if row.get("id") is not None}
    if not unique:
        raise CustomerNotFound(requested_name)
    if len(unique) > 1:
        raise CustomerAmbiguous(list(unique.values()))
    return client.get_customer(next(iter(unique)))


def customer_data(client: ReadOnlyClient, requested_name: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    customer = resolve_customer(client, requested_name)
    customer_id = int(customer["id"])
    quotations = client.list_quotations(customer_id)
    orders = client.list_orders(customer_id)
    return customer, quotations, orders


def linked_quotation_ids(quotations: list[dict[str, Any]], orders: list[dict[str, Any]]) -> set[int]:
    quotation_ids = {int(item["id"]) for item in quotations if item.get("id") is not None}
    return {
        int(order["quotation_id"])
        for order in orders
        if order.get("quotation_id") is not None
        and int(order["quotation_id"]) in quotation_ids
    }


def customer_overview(client: ReadOnlyClient, name: str) -> str:
    customer, quotations, orders = customer_data(client, name)
    status_counts = Counter(str(order.get("status", "unknown")) for order in orders)
    status_summary = "、".join(f"{status} {count} 筆" for status, count in sorted(status_counts.items())) or "無訂單"
    q_total = sum((money(row.get("total_price")) for row in quotations), Decimal("0"))
    o_total = sum((money(row.get("total_price")) for row in orders), Decimal("0"))
    return (
        f"客戶銷售概況：{customer.get('name', '名稱未提供')}\n"
        f"客戶等級：{customer.get('level', '未提供')}\n"
        f"信用評分：{customer.get('credit_score', '未提供')}\n"
        f"報價單數量：{len(quotations)}\n"
        f"訂單數量：{len(orders)}\n"
        f"報價總額：{display_number(q_total)}\n"
        f"訂單總額：{display_number(o_total)}\n"
        f"訂單狀態摘要：{status_summary}"
    )


def quotation_history(client: ReadOnlyClient, name: str) -> str:
    customer, quotations, _ = customer_data(client, name)
    lines = [f"{customer.get('name', name)} 的報價歷史（{len(quotations)} 筆）："]
    for item in quotations:
        lines.append(
            f"- {item.get('quotation_number', '編號未提供')}｜狀態：{item.get('status', '未提供')}｜"
            f"總價：{display_number(money(item.get('total_price')))}｜建立日期：{display_date(item.get('created_at'))}"
        )
    if not quotations:
        lines.append("目前沒有報價單資料。")
    return "\n".join(lines)


def order_history(client: ReadOnlyClient, name: str) -> str:
    customer, _, orders = customer_data(client, name)
    lines = [f"{customer.get('name', name)} 的訂單歷史（{len(orders)} 筆）："]
    for item in orders:
        quotation_id = item.get("quotation_id")
        if quotation_id is None:
            linked = "獨立訂單（沒有關聯報價單）"
        else:
            quotation = client.get_quotation(int(quotation_id))
            linked = f"關聯報價單：{quotation.get('quotation_number', f'ID {quotation_id}')}"
        lines.append(
            f"- {item.get('order_number', '編號未提供')}｜狀態：{item.get('status', '未提供')}｜"
            f"總價：{display_number(money(item.get('total_price')))}｜建立日期：{display_date(item.get('created_at'))}｜{linked}"
        )
    if not orders:
        lines.append("目前沒有訂單資料。")
    return "\n".join(lines)


def conversion_analysis(client: ReadOnlyClient, name: str) -> str:
    customer, quotations, orders = customer_data(client, name)
    converted_ids = linked_quotation_ids(quotations, orders)
    converted = [row for row in quotations if row.get("id") is not None and int(row["id"]) in converted_ids]
    pending = [row for row in quotations if row.get("id") is None or int(row["id"]) not in converted_ids]
    lines = [f"{customer.get('name', name)} 的報價轉訂單分析：已轉換 {len(converted)} / {len(quotations)} 張報價單。", "已關聯訂單："]
    lines.extend(f"- {row.get('quotation_number', '編號未提供')}" for row in converted)
    if not converted:
        lines.append("- 無")
    lines.append("尚未關聯訂單：")
    lines.extend(f"- {row.get('quotation_number', '編號未提供')}" for row in pending)
    if not pending:
        lines.append("- 無")
    return "\n".join(lines)


def compare_customers(client: ReadOnlyClient, first_name: str, second_name: str) -> str:
    first = customer_data(client, first_name)
    second = customer_data(client, second_name)
    lines = ["客戶銷售活動比較："]
    for customer, quotations, orders in (first, second):
        q_total = sum((money(row.get("total_price")) for row in quotations), Decimal("0"))
        o_total = sum((money(row.get("total_price")) for row in orders), Decimal("0"))
        conversions = len(linked_quotation_ids(quotations, orders))
        lines.extend(
            [
                f"\n{customer.get('name', '名稱未提供')}：",
                f"客戶等級：{customer.get('level', '未提供')}；信用評分：{customer.get('credit_score', '未提供')}",
                f"報價單數量：{len(quotations)}；報價總額：{display_number(q_total)}",
                f"訂單數量：{len(orders)}；訂單總額：{display_number(o_total)}",
                f"已關聯轉換報價單數：{conversions}",
            ]
        )
    return "\n".join(lines)
