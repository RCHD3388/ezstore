"""Verify one quotation A2A exchange and read-only/source integrity evidence."""

import argparse
import ast
import asyncio
import hashlib
from importlib.util import resolve_name
import json
import re
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import ListTasksRequest, Role, TaskState
from google.protobuf.json_format import MessageToDict

from ezstore_a2a_coordinator.a2a_transport import _card_location, _extract_response
from ezstore_a2a_coordinator.routing import quotation_subrequest

REPO = Path(__file__).resolve().parents[3]
APP = REPO / "a2a_app"
PROTECTED = [
    "agent", "agent2", "frontend", "backend", "mcp_server",
    "scripts/seed-test-data.sql", "docker-compose.yml", "docker-compose.build.yml",
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def command(args):
    result = subprocess.run(args, cwd=REPO, capture_output=True, check=True)
    return result.stdout


def protected_snapshot():
    files = command(["git", "ls-files", "-z", "--", *PROTECTED]).decode().split("\0")
    return {
        "tracked_files": {name: digest((REPO / name).read_bytes()) for name in files if name},
        "git_status": command([
            "git", "status", "--porcelain=v1", "--untracked-files=all", "--", *PROTECTED
        ]).decode(),
    }


def previous_evidence_snapshot():
    return {
        str(path.relative_to(APP)): digest(path.read_bytes())
        for path in sorted((APP / "artifacts").rglob("*"))
        if path.is_file() and "stage4" not in path.relative_to(APP / "artifacts").parts
    }


def database_snapshot():
    # pg_dump reads data; its SQL output is hashed, never restored or executed.
    dump = command([
        "docker", "compose", "exec", "-T", "db", "sh", "-c",
        'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" '
        '--data-only --column-inserts --no-owner --no-privileges',
    ]).decode("utf-8")
    lines = [line for line in dump.splitlines()
             if not line.startswith(("\\restrict ", "\\unrestrict "))]
    normalized = "\n".join(lines).encode("utf-8")
    tables = sorted(re.findall(r"^-- Data for Name: ([^;]+);", dump, re.MULTILINE))
    if not tables:
        raise RuntimeError("Database snapshot did not contain any application tables.")
    return {
        "method": "Verifier-only PostgreSQL data/sequence dump; no restore or write",
        "sha256": digest(normalized), "bytes": len(normalized), "tables": tables,
        "normalization": "Line endings and random pg_dump restrict/unrestrict tokens only",
    }


def coordinator_source_audit():
    package = APP / "ezstore_a2a_coordinator"
    pending = [package / "__init__.py", package / "agent.py", package / "fast_api_app.py"]
    inspected = {}
    forbidden = []
    forbidden_roots = {
        "backend", "mcp", "mcp_server", "quotation_agent", "sales_insight_agent",
        "requests", "sqlite3", "psycopg", "psycopg2",
    }

    def local_module(name):
        candidate = APP.joinpath(*name.split("."))
        if candidate.with_suffix(".py").is_file():
            return candidate.with_suffix(".py")
        if (candidate / "__init__.py").is_file():
            return candidate / "__init__.py"
        return None

    while pending:
        path = pending.pop()
        if str(path) in inspected:
            continue
        data = path.read_bytes()
        inspected[str(path)] = digest(data)
        source = data.decode("utf-8")
        if re.search(r"BACKEND_URL|MCP_URL|/api/v1|localhost:(?:8080|8010)\b", source):
            forbidden.append({"file": str(path.relative_to(APP)), "reason": "business endpoint literal"})
        for node in ast.walk(ast.parse(source)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    context = ".".join(path.parent.relative_to(APP).parts)
                    module = resolve_name("." * node.level + module, context)
                if module:
                    modules = [module] + [module + "." + alias.name for alias in node.names]
            for module in modules:
                if (module.split(".")[0] in forbidden_roots or ".mcp" in module
                        or module == "urllib.request" or module.startswith("urllib.request.")):
                    forbidden.append({"file": str(path.relative_to(APP)), "import": module})
                if module.startswith("ezstore_a2a_coordinator"):
                    target = local_module(module)
                    if target:
                        pending.append(target)
    return {
        "entrypoints": ["agent.py", "fast_api_app.py"],
        "reachable_source_hashes": {
            str(Path(name).relative_to(APP)): value for name, value in sorted(inspected.items())
        },
        "forbidden_findings": forbidden,
        "note": "Coordinator entrypoints and local import closure; dormant experimental services are not loaded",
    }


async def verify(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = output / "verification.json"
    if report.exists():
        raise RuntimeError("Refusing to overwrite an existing verification run.")
    evidence = {"scope": "quotation-only Stage 4", "checks": {}, "events": []}

    def save():
        report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    evidence["protected_before"] = protected_snapshot()
    evidence["previous_artifacts_before"] = previous_evidence_snapshot()
    evidence["source_audit"] = coordinator_source_audit()
    xml = ET.parse(args.unit_report).getroot()
    suites = [xml] if xml.tag == "testsuite" else list(xml.iter("testsuite"))
    evidence["unit_tests"] = {
        key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
        for key in ["tests", "failures", "errors", "skipped"]
    }
    evidence["checks"]["unit_tests"] = (
        evidence["unit_tests"]["tests"] > 0
        and evidence["unit_tests"]["failures"] == evidence["unit_tests"]["errors"] == 0
    )
    evidence["checks"]["no_direct_backend_mcp_fallback"] = (
        not evidence["source_audit"]["forbidden_findings"]
        and evidence["checks"]["unit_tests"]
    )
    save()
    if not all(evidence["checks"].values()):
        raise RuntimeError("Static/unit preflight failed; no live lookup sent.")

    evidence["backend_before"] = database_snapshot()
    save()
    try:
        async with httpx.AsyncClient(timeout=240) as http:
            base, path = _card_location(args.card_url)
            card = await A2ACardResolver(http, base, agent_card_path=path).get_agent_card()
            evidence["card_url"] = args.card_url
            evidence["agent_card"] = MessageToDict(card)
            evidence["checks"]["agent_card_discovery"] = (
                card.name == "quotation_agent"
                and any(i.protocol_binding == "JSONRPC" for i in card.supported_interfaces)
            )
            save()
            if not evidence["checks"]["agent_card_discovery"]:
                raise RuntimeError("Unexpected quotation Agent Card; no lookup sent.")
            client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(card)

            async def tasks():
                token = ""
                seen = set()
                result = []
                while True:
                    page = await client.list_tasks(ListTasksRequest(
                        page_size=100, page_token=token, history_length=100, include_artifacts=True
                    ))
                    result.extend(page.tasks)
                    token = page.next_page_token
                    if not token:
                        return result
                    if token in seen:
                        raise RuntimeError("Repeated A2A task-list pagination token.")
                    seen.add(token)

            try:
                before = {task.id for task in await tasks()}
                user = "stage4-quotation-" + uuid.uuid4().hex
                session = await http.post(
                    f"{args.coordinator}/apps/ezstore_a2a_coordinator/users/{user}/sessions", json={}
                )
                session.raise_for_status()
                evidence["session_id"] = session.json()["id"]
                prompt = "Show me quotation QT-20260330-001."
                evidence["prompt"] = prompt
                evidence["lookup_requests_sent"] = 1
                save()
                async with http.stream("POST", args.coordinator + "/run_sse", json={
                    "app_name": "ezstore_a2a_coordinator", "user_id": user,
                    "session_id": evidence["session_id"],
                    "new_message": {"role": "user", "parts": [{"text": prompt}]},
                    "streaming": True,
                }) as response:
                    evidence["coordinator_http_status"] = response.status_code
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            event = json.loads(line[5:].strip())
                            evidence["events"].append(event)
                            delta = (event.get("actions") or {}).get("stateDelta", {})
                            if "resolved_route" in delta:
                                evidence["route"] = delta["resolved_route"]
                            if "/respond@" in (event.get("nodeInfo") or {}).get("path", ""):
                                evidence["reply"] = "\n".join(
                                    p["text"] for p in (event.get("content") or {}).get("parts", [])
                                    if p.get("text")
                                )
                            save()
                new_tasks = [task for task in await tasks() if task.id not in before]
                evidence["a2a_tasks"] = [MessageToDict(task) for task in new_tasks]
                completed = [task for task in new_tasks
                             if task.status.state == TaskState.TASK_STATE_COMPLETED]
                evidence["checks"]["a2a_message_exchange"] = (
                    evidence.get("route") == "quotation_only"
                    and len(new_tasks) == len(completed) == 1
                    and any(
                        message.role == Role.ROLE_USER
                        and "".join(part.text for part in message.parts) == quotation_subrequest(prompt)
                        for message in completed[0].history
                    )
                )
                remote = _extract_response(completed, "quotation_agent") if completed else ""
                evidence["remote_result"] = remote
                evidence["checks"]["returned_quotation_result"] = (
                    bool(remote) and evidence.get("reply") == remote
                    and "QT-20260330-001" in remote
                    and bool(re.search(r"https?://[^\s]+/quotations/\d+", remote))
                )
                save()
            finally:
                await client.close()
    except Exception as exc:
        evidence["error"] = {"type": type(exc).__name__, "message": str(exc)}
        save()
    finally:
        evidence["backend_after"] = database_snapshot()
        evidence["protected_after"] = protected_snapshot()
        evidence["previous_artifacts_after"] = previous_evidence_snapshot()
        evidence["checks"]["backend_data_unchanged"] = (
            evidence["backend_before"] == evidence["backend_after"]
        )
        evidence["checks"]["protected_files_unchanged"] = (
            evidence["protected_before"] == evidence["protected_after"]
            and not evidence["protected_after"]["git_status"]
        )
        evidence["checks"]["previous_evidence_unchanged"] = (
            evidence["previous_artifacts_before"] == evidence["previous_artifacts_after"]
        )
        required = [
            "unit_tests", "agent_card_discovery", "a2a_message_exchange",
            "returned_quotation_result", "no_direct_backend_mcp_fallback",
            "backend_data_unchanged", "protected_files_unchanged", "previous_evidence_unchanged",
        ]
        evidence["passed"] = not evidence.get("error") and all(
            evidence["checks"].get(name, False) for name in required
        )
        save()
    print(json.dumps({"report": str(report), "passed": evidence["passed"],
                      "checks": evidence["checks"], "error": evidence.get("error"),
                      "task_ids": [task.get("id") for task in evidence.get("a2a_tasks", [])]},
                     ensure_ascii=True, indent=2))
    if not evidence["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--unit-report", required=True)
    parser.add_argument("--coordinator", default="http://127.0.0.1:8013")
    parser.add_argument("--card-url", default=(
        "http://127.0.0.1:8011/a2a/quotation_agent/.well-known/agent-card.json"
    ))
    asyncio.run(verify(parser.parse_args()))
