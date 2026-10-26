"""Read-only Backend REST client. The only supported HTTP verb is GET."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


class BackendAPIError(RuntimeError):
    """Raised when the configured Backend cannot return valid API data."""


class ReadOnlyBackendClient:
    """A narrow client exposing only the REST API's read operations."""

    _PATH_PATTERN = re.compile(r"^/(customers|quotations|orders)(?:/\d+)?$")

    def __init__(self, base_url: str | None = None, timeout: float = 10.0):
        self.base_url = (base_url or os.getenv(
            "BACKEND_URL", "http://localhost:8080/api/v1"
        )).rstrip("/") + "/"
        self.timeout = timeout

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self._PATH_PATTERN.fullmatch(path):
            raise ValueError("Backend path is not on the read-only allowlist")
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        url = urljoin(self.base_url, path.lstrip("/"))
        if query:
            url = f"{url}?{query}"
        request = Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BackendAPIError(f"Backend GET {path} failed: {exc}") from exc

    @staticmethod
    def _page(payload: Any) -> tuple[list[dict[str, Any]], int | None, int | None]:
        if isinstance(payload, list):
            return payload, None, None
        if not isinstance(payload, dict):
            raise BackendAPIError("Backend returned an unexpected response shape")
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise BackendAPIError("Backend list response did not contain a data array")
        total = payload.get("total")
        page_size = payload.get("page_size")
        return data, int(total) if total is not None else None, int(page_size) if page_size else None

    def _get_all(self, path: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        page = 1
        page_size = 100
        while True:
            payload = self._get_json(path, {**(filters or {}), "page": page, "page_size": page_size})
            rows, total, returned_page_size = self._page(payload)
            collected.extend(rows)
            if total is None:
                if len(rows) < (returned_page_size or page_size):
                    return collected
            elif len(collected) >= total:
                return collected
            if not rows:
                return collected
            page += 1

    @staticmethod
    def _unwrap_detail(payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return payload["data"]
        if isinstance(payload, dict):
            return payload
        raise BackendAPIError("Backend detail response was not an object")

    def search_customers(self, name: str) -> list[dict[str, Any]]:
        return self._get_all("/customers", {"search": name})

    def get_customer(self, customer_id: int) -> dict[str, Any]:
        return self._unwrap_detail(self._get_json(f"/customers/{int(customer_id)}"))

    def list_quotations(self, customer_id: int) -> list[dict[str, Any]]:
        return self._get_all("/quotations", {"customer_id": int(customer_id)})

    def list_orders(self, customer_id: int) -> list[dict[str, Any]]:
        return self._get_all("/orders", {"customer_id": int(customer_id)})

    def get_quotation(self, quotation_id: int) -> dict[str, Any]:
        return self._unwrap_detail(self._get_json(f"/quotations/{int(quotation_id)}"))

    def get_order(self, order_id: int) -> dict[str, Any]:
        return self._unwrap_detail(self._get_json(f"/orders/{int(order_id)}"))
