"""Record one live Customer Overview A2A flow and quotation regression.

Run from a2a_app. Every result goes to a new directory; no old evidence is changed.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import ListTasksRequest, Role, TaskState
from google.protobuf.json_format import MessageToDict

from ezstore_a2a_coordinator.a2a_transport import _card_location, _extract_response
from ezstore_a2a_coordinator.dispatch import OFF_TOPIC_REFUSAL, WRITE_REFUSAL


APP = Path(__file__).resolve().parents[2]
REPO = APP.parent
PROTECTED = (
    "agent", "agent2", "okf_app", "frontend", "backend", "mcp_server",
    "scripts/seed-test-data.sql", "docker-compose.yml", "docker-compose.build.yml",
)
SALES_CARD = "http://127.0.0.1:8012/.well-known/agent-card.json"
QUOTE_CARD = "http://127.0.0.1:8011/a2a/quotation_agent/.well-known/agent-card.json"
COORDINATOR = "http://127.0.0.1:8013"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(paths: tuple[str, ...]) -> dict:
    files = subprocess.run(
        ["git", "ls-files", "-z", "--", *paths], cwd=REPO,
        check=True, capture_output=True,
    ).stdout.decode().split("\0")
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", *paths],
        cwd=REPO, check=True, capture_output=True,
    ).stdout.decode()
    return {
        "tracked_files": {name: sha((REPO / name).read_bytes()) for name in files if name},
        "git_status": status,
    }


def previous_evidence() -> dict[str, str]:
    return {
        str(path.relative_to(APP)): sha(path.read_bytes())
        for path in sorted((APP / "artifacts").rglob("*"))
        if path.is_file() and "customer-overview-" not in str(path.relative_to(APP / "artifacts"))
    }


def no_direct_fallback() -> dict:
    files = (
        "agent.py", "fast_api_app.py", "workflow.py", "routing.py", "dispatch.py",
        "a2a_transport.py", "config.py", "app_utils/a2a.py", "app_utils/services.py",
    )
    forbidden = []
    for name in files:
        source = (APP / "ezstore_a2a_coordinator" / name).read_text(encoding="utf-8")
        if re.search(r"BACKEND_URL|MCP_URL|/api/v1|localhost:(?:8080|8010)\b", source):
            forbidden.append({"file": name, "reason": "business endpoint literal"})
        for node in ast.walk(ast.parse(source)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.split(".")[0] in {
                    "backend", "mcp", "mcp_server", "sales_insight_agent",
                    "quotation_agent", "requests", "sqlite3", "psycopg", "psycopg2",
                }:
                    forbidden.append({"file": name, "import": module})
    return {"files": list(files), "findings": forbidden, "passed": not forbidden}


async def tasks(client) -> list:
    found = []
    token = ""
    seen = set()
    while True:
        page = await client.list_tasks(ListTasksRequest(
            page_size=100, page_token=token, history_length=100, include_artifacts=True
        ))
        found.extend(page.tasks)
        token = page.next_page_token
        if not token:
            return found
        if token in seen:
            raise RuntimeError("Repeated A2A task pagination token.")
        seen.add(token)


async def coordinator_case(http, prompt: str) -> dict:
    user = "customer-a2a-" + uuid.uuid4().hex
    session = await http.post(
        f"{COORDINATOR}/apps/ezstore_a2a_coordinator/users/{user}/sessions", json={}
    )
    session.raise_for_status()
    case = {"prompt": prompt, "session_id": session.json()["id"], "route": None, "reply": None}
    async with http.stream("POST", COORDINATOR + "/run_sse", json={
        "app_name": "ezstore_a2a_coordinator", "user_id": user,
        "session_id": case["session_id"],
        "new_message": {"role": "user", "parts": [{"text": prompt}]},
        "streaming": True,
    }) as response:
        case["http_status"] = response.status_code
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            delta = (event.get("actions") or {}).get("stateDelta", {})
            case["route"] = delta.get("resolved_route", case["route"])
            if "/respond@" in (event.get("nodeInfo") or {}).get("path", ""):
                case["reply"] = "\n".join(
                    part["text"] for part in (event.get("content") or {}).get("parts", [])
                    if part.get("text")
                )
    return case


async def resolve(http, url: str):
    base, path = _card_location(url)
    return await A2ACardResolver(http, base, agent_card_path=path).get_agent_card()


async def verify(output: Path) -> dict:
    report_path = output / "verification.json"
    if report_path.exists():
        raise FileExistsError(f"Refusing to overwrite {report_path}")
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "scope": "Customer Overview through existing Coordinator -> A2A -> Sales Insight Agent",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "protocol": "A2A JSON-RPC 1.0",
        "endpoints": {"coordinator": COORDINATOR, "sales_agent_card": SALES_CARD,
                      "sales_a2a": "http://127.0.0.1:8012/a2a/sales_insight_agent",
                      "quotation_agent_card": QUOTE_CARD},
        "checks": {},
    }

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report["protected_before"] = snapshot(PROTECTED)
    report["previous_evidence_before"] = previous_evidence()
    report["fallback_audit"] = no_direct_fallback()
    report["checks"]["no_direct_backend_mcp_fallback"] = report["fallback_audit"]["passed"]
    save()
    try:
        async with httpx.AsyncClient(timeout=240) as http:
            sales_card = await resolve(http, SALES_CARD)
            quotation_card = await resolve(http, QUOTE_CARD)
            report["sales_agent_card"] = MessageToDict(sales_card)
            report["quotation_agent_card"] = MessageToDict(quotation_card)
            report["checks"]["sales_card_discovery"] = (
                sales_card.name == "sales_insight_agent"
                and [skill.id for skill in sales_card.skills] == ["customer_overview"]
                and any(i.protocol_binding == "JSONRPC" for i in sales_card.supported_interfaces)
            )
            report["checks"]["quotation_card_discovery"] = (
                quotation_card.name == "quotation_agent"
                and any(i.protocol_binding == "JSONRPC" for i in quotation_card.supported_interfaces)
            )
            save()
            if not all(report["checks"].values()):
                raise RuntimeError("Preflight card/fallback check failed; no task sent.")

            sales_client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(sales_card)
            quotation_client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(quotation_card)
            try:
                sales_before = {task.id for task in await tasks(sales_client)}
                quotation_before = {task.id for task in await tasks(quotation_client)}
                prompt = "Give me an overview of customer 史塔克工業."
                report["customer_overview"] = await coordinator_case(http, prompt)
                save()
                new_sales = [task for task in await tasks(sales_client) if task.id not in sales_before]
                report["sales_a2a_tasks"] = [MessageToDict(task) for task in new_sales]
                completed = [task for task in new_sales if task.status.state == TaskState.TASK_STATE_COMPLETED]
                report["sales_remote_result"] = _extract_response(completed, "sales_insight_agent") if completed else ""
                report["checks"]["sales_a2a_message_exchange"] = (
                    len(new_sales) == len(completed) == 1
                    and any(m.role == Role.ROLE_USER and "".join(p.text for p in m.parts) == prompt
                            for m in completed[0].history)
                )
                report["checks"]["customer_overview_result"] = (
                    report["customer_overview"]["route"] == "customer_insight_only"
                    and report["customer_overview"]["reply"] == report["sales_remote_result"]
                    and "史塔克工業" in report["sales_remote_result"]
                    and all(label in report["sales_remote_result"] for label in (
                        "客戶等級", "信用評分", "報價單數量", "訂單數量", "報價總額", "訂單總額", "訂單狀態摘要"
                    ))
                )
                save()

                after_overview = {task.id for task in await tasks(sales_client)}
                report["unsupported"] = await coordinator_case(http, "List customer 史塔克工業 order history.")
                new_unsupported = [task for task in await tasks(sales_client) if task.id not in after_overview]
                report["unsupported_a2a_tasks"] = [MessageToDict(task) for task in new_unsupported]
                report["checks"]["unsupported_refused"] = (
                    report["unsupported"]["route"] == "customer_insight_only"
                    and "Customer Overview only" in (report["unsupported"]["reply"] or "")
                    and len(new_unsupported) == 1
                    and new_unsupported[0].status.state == TaskState.TASK_STATE_COMPLETED
                )
                save()

                after_unsupported = {task.id for task in await tasks(sales_client)}
                report["write"] = await coordinator_case(http, "Please modify customer 史塔克工業.")
                report["off_topic"] = await coordinator_case(http, "What is the weather today?")
                report["checks"]["write_and_off_topic_refused"] = (
                    report["write"]["route"] == "write_request"
                    and report["write"]["reply"] == WRITE_REFUSAL
                    and report["off_topic"]["route"] == "off_topic"
                    and report["off_topic"]["reply"] == OFF_TOPIC_REFUSAL
                    and {task.id for task in await tasks(sales_client)} == after_unsupported
                )
                save()

                quote_prompt = "Show me quotation QT-20260330-001."
                report["quotation_regression"] = await coordinator_case(http, quote_prompt)
                new_quote = [task for task in await tasks(quotation_client)
                             if task.id not in quotation_before]
                report["quotation_a2a_tasks"] = [MessageToDict(task) for task in new_quote]
                quote_completed = [task for task in new_quote
                                   if task.status.state == TaskState.TASK_STATE_COMPLETED]
                quote_text = _extract_response(quote_completed, "quotation_agent") if quote_completed else ""
                report["quotation_remote_result"] = quote_text
                report["checks"]["quotation_regression"] = (
                    report["quotation_regression"]["route"] == "quotation_only"
                    and len(new_quote) == len(quote_completed) == 1
                    and report["quotation_regression"]["reply"] == quote_text
                    and "QT-20260330-001" in quote_text
                    and bool(re.search(r"https?://[^\s]+/quotations/\d+", quote_text))
                )
                save()
            finally:
                await sales_client.close()
                await quotation_client.close()
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        report["protected_after"] = snapshot(PROTECTED)
        report["previous_evidence_after"] = previous_evidence()
        report["checks"]["protected_files_unchanged"] = (
            report["protected_before"] == report["protected_after"]
            and not report["protected_after"]["git_status"]
        )
        report["checks"]["previous_evidence_unchanged"] = (
            report["previous_evidence_before"] == report["previous_evidence_after"]
        )
        required = (
            "sales_card_discovery", "sales_a2a_message_exchange", "customer_overview_result",
            "unsupported_refused", "write_and_off_topic_refused", "quotation_card_discovery",
            "quotation_regression", "no_direct_backend_mcp_fallback",
            "protected_files_unchanged", "previous_evidence_unchanged",
        )
        report["passed"] = not report.get("error") and all(
            report["checks"].get(key, False) for key in required
        )
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(verify(args.output.resolve()))
    print(json.dumps({"passed": result["passed"], "checks": result["checks"],
                      "error": result.get("error"),
                      "sales_task_ids": [t["id"] for t in result.get("sales_a2a_tasks", [])],
                      "quotation_task_ids": [t["id"] for t in result.get("quotation_a2a_tasks", [])]},
                     ensure_ascii=True, indent=2))
    if not result["passed"]:
        raise SystemExit(1)
