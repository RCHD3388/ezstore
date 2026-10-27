"""One quotation-only Stage 3 run; no business-action or Gemini retry loop.

Run from a2a_app with the Coordinator and quotation A2A service already running.
Task listing reads protocol evidence; only the Coordinator sends the lookup.
"""

import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import ListTasksRequest, TaskState
from google.protobuf.json_format import MessageToDict

from ezstore_a2a_coordinator.a2a_transport import _card_location, _extract_response
from ezstore_a2a_coordinator.dispatch import OFF_TOPIC_REFUSAL, WRITE_REFUSAL


async def main():
    coordinator = os.getenv("COORDINATOR_URL", "http://127.0.0.1:8013")
    card_url = os.getenv(
        "QUOTATION_AGENT_CARD_URL",
        "http://127.0.0.1:8011/a2a/quotation_agent/.well-known/agent-card.json",
    )
    folder = Path("artifacts/stage3")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (
        "quotation-only-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    evidence = {"scope": "quotation-only revised Stage 3", "cases": {}, "checks": {}}

    def save():
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    async with httpx.AsyncClient(timeout=240) as http:
        base, card_path = _card_location(card_url)
        card = await A2ACardResolver(http, base, agent_card_path=card_path).get_agent_card()
        evidence["agent_card_url"] = card_url
        evidence["agent_card"] = MessageToDict(card)
        evidence["checks"]["quotation_agent_card"] = (
            card.name == "quotation_agent"
            and any(i.protocol_binding == "JSONRPC" for i in card.supported_interfaces)
        )
        save()
        client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(card)

        async def tasks():
            response = await client.list_tasks(
                ListTasksRequest(page_size=100, history_length=20, include_artifacts=True)
            )
            if response.next_page_token:
                raise RuntimeError("Unexpected task pagination; do not infer a complete snapshot.")
            return list(response.tasks)

        async def run_case(name, prompt):
            user = "stage3-quotation-" + uuid.uuid4().hex
            session = await http.post(
                f"{coordinator}/apps/ezstore_a2a_coordinator/users/{user}/sessions", json={}
            )
            session.raise_for_status()
            case = {"prompt": prompt, "session_id": session.json()["id"], "events": []}
            evidence["cases"][name] = case
            save()
            async with http.stream(
                "POST", coordinator + "/run_sse",
                json={
                    "app_name": "ezstore_a2a_coordinator", "user_id": user,
                    "session_id": case["session_id"],
                    "new_message": {"role": "user", "parts": [{"text": prompt}]},
                    "streaming": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        case["events"].append(json.loads(line[5:].strip()))
                        save()
            for event in case["events"]:
                delta = (event.get("actions") or {}).get("stateDelta", {})
                if "resolved_route" in delta:
                    case["route"] = delta["resolved_route"]
                if "/respond@" in (event.get("nodeInfo") or {}).get("path", ""):
                    case["reply"] = "\n".join(
                        part["text"] for part in (event.get("content") or {}).get("parts", [])
                        if part.get("text")
                    )
            save()
            return case

        try:
            before = {task.id for task in await tasks()}
            quotation = await run_case("quotation_only", "Show me quotation QT-20260330-001.")
            after_quotation = await tasks()
            new_tasks = [task for task in after_quotation if task.id not in before]
            evidence["quotation_a2a_tasks"] = [MessageToDict(task) for task in new_tasks]
            completed = [t for t in new_tasks if t.status.state == TaskState.TASK_STATE_COMPLETED]
            remote_text = _extract_response(completed, "quotation_agent") if completed else ""
            evidence["remote_result"] = remote_text
            evidence["checks"]["quotation_through_a2a"] = (
                quotation.get("route") == "quotation_only"
                and len(new_tasks) == 1 and len(completed) == 1
                and quotation.get("reply") == remote_text
                and "QT-20260330-001" in remote_text
                and bool(re.search(r"https?://[^\s]+/quotations/\d+", remote_text))
            )
            save()
            refusal_cases = [
                ("off_topic", "What is the weather today?", "off_topic", OFF_TOPIC_REFUSAL),
                ("reject_write_request", "Please duplicate quotation QT-20260330-001.",
                 "write_request", WRITE_REFUSAL),
            ]
            ids_after_quote = {task.id for task in after_quotation}
            for name, prompt, route, reply in refusal_cases:
                case = await run_case(name, prompt)
                unchanged = {task.id for task in await tasks()} == ids_after_quote
                evidence["checks"][name] = (
                    case.get("route") == route and case.get("reply") == reply and unchanged
                )
                save()
        except Exception as exc:
            evidence["error"] = {"type": type(exc).__name__, "message": str(exc)}
            save()
            raise
        finally:
            await client.close()
    print(json.dumps({"artifact": str(path), "checks": evidence["checks"],
                      "remote_result": evidence.get("remote_result"),
                      "cases": {k: {key: value for key, value in v.items() if key != "events"}
                                for k, v in evidence["cases"].items()}}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
