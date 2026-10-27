"""Stage 4 evidence producer. Uses the unchanged validator and consumer locally."""

import argparse
import builtins
import hashlib
import http.client
import io
import json
import os
import re
import socket
import subprocess
import xml.etree.ElementTree as ET
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from .consumer import DEFAULT_BUNDLE, KnowledgeConsumer
from .validator import CONCEPT_FILES, validate_bundle

CASES = [
    ("What is the default pricing factor for a VIP customer?", "quotation-pricing.md",
     ["`vip`", "0.80"]),
    ("What is the difference between a draft and published quotation?", "quotation-lifecycle.md",
     ["`draft`", "`published`", "may be edited, deleted, or published", "cannot be modified"]),
    ("Can a published quotation be modified?", "quotation-lifecycle.md",
     ["`published`", "cannot be modified"]),
    ("How can a quotation relate to an order?", "quotation-order-relationship.md",
     ["order.quotation_id", "quotation.id", "quotation_id = null", "standalone order"]),
]
UNSUPPORTED = [
    "What is the weather?", "What is a VIP customer's credit limit?",
    "What is the tax rate?", "How many quotations are there?",
    "What is the current credit score of customer Stark?",
    "What is customer Stark's credit score?",
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare_manifest(root, manifest):
    changed = [name for name, expected in manifest.items()
               if not (root / name).is_file() or sha256(root / name) != expected]
    return {"files": len(manifest), "changed": changed, "passed": not changed}


@contextmanager
def audit_access():
    """Monitor the actual consumption run; reject writes and outbound networking."""
    observed = {"file_reads": 0, "write_attempts": [], "network_attempts": []}
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

    def blocked(kind, operation):
        observed[kind].append(operation)
        raise AssertionError(f"Read-only knowledge access attempted {operation}")

    def opening(original):
        def wrapped(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                blocked("write_attempts", "file open for writing")
            observed["file_reads"] += 1
            return original(file, mode, *args, **kwargs)
        return wrapped

    def os_open(file, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            blocked("write_attempts", "os.open for writing")
        observed["file_reads"] += 1
        return real_os_open(file, flags, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch("builtins.open", opening(real_open)))
        stack.enter_context(patch("io.open", opening(real_io_open)))
        stack.enter_context(patch("os.open", os_open))
        for operation in ["remove", "unlink", "rename", "replace", "mkdir", "rmdir"]:
            stack.enter_context(patch.object(os, operation,
                lambda *a, _op=operation, **k: blocked("write_attempts", "os." + _op)))
        for operation in ["socket", "create_connection"]:
            stack.enter_context(patch.object(socket, operation,
                lambda *a, _op=operation, **k: blocked("network_attempts", "socket." + _op)))
        stack.enter_context(patch.object(subprocess, "Popen",
                            lambda *a, **k: blocked("write_attempts", "subprocess launch")))
        yield observed


def observe_knowledge(bundle_root):
    root = Path(bundle_root)
    before = {p.relative_to(root).as_posix(): sha256(p) for p in root.rglob("*") if p.is_file()}
    result = {"concepts": [], "cases": [], "unsupported": [], "write_requests": []}
    with audit_access() as access:
        try:
            validation = validate_bundle(root)
            result["validation"] = validation.summary()
            if not validation.valid:
                raise ValueError("Bundle validation failed; consumer checks were not run.")
            consumer = KnowledgeConsumer(root)
            for concept in consumer.concepts():
                document = consumer.document(concept["document"])
                result["concepts"].append({**concept, "type": document.metadata.get("type"),
                    "body_bytes": len(document.body.encode()),
                    "passed": bool(document.body.strip()) and bool(document.metadata.get("type"))})
            for question, expected_document, needles in CASES:
                answer = consumer.answer(question)
                lines = set(consumer.document(expected_document).body.splitlines())
                grounded = all(line in lines for line in answer.markdown.splitlines() if line)
                result["cases"].append({**asdict(answer), "grounded_in_source": grounded,
                    "expected_document": expected_document, "expected_terms": needles,
                    "passed": answer.supported and answer.document == expected_document
                    and grounded and all(term in answer.markdown for term in needles)})
            for question in UNSUPPORTED:
                answer = consumer.answer(question)
                result["unsupported"].append({**asdict(answer), "passed":
                    not answer.supported and answer.document is None and not answer.sources
                    and bool(re.search(r"outside|read-only", answer.markdown))
                    and not re.search(r"\d", answer.markdown)})
            for question in ["Please modify quotation QT-20260330-001.", "Delete customer Stark."]:
                answer = consumer.answer(question)
                result["write_requests"].append({**asdict(answer), "passed":
                    not answer.supported and "read-only" in answer.markdown})
        except Exception as exc:
            result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    after = {p.relative_to(root).as_posix(): sha256(p) for p in root.rglob("*") if p.is_file()}
    result["access"] = access
    result["bundle_before"] = before
    result["bundle_after"] = after
    result["read_only_passed"] = (
        not result.get("error") and before == after and access["file_reads"] > 0
        and not access["write_attempts"] and not access["network_attempts"]
        and len(result["write_requests"]) == 2 and all(c["passed"] for c in result["write_requests"])
    )
    return result


def service_observation():
    result = {"url": "http://127.0.0.1:8020/"}
    try:
        pid = subprocess.check_output([
            "powershell", "-NoProfile", "-Command",
            "(Get-NetTCPConnection -State Listen -LocalPort 8020 -ErrorAction Stop | "
            "Select-Object -First 1).OwningProcess",
        ], timeout=15).decode().strip()
        result["pid"] = int(pid)
        connection = http.client.HTTPConnection("127.0.0.1", 8020, timeout=5)
        try:
            connection.request("GET", "/api/concepts")
            response = connection.getresponse()
            result["http_status"] = response.status
            result["concept_count"] = len(json.loads(response.read()))
        finally:
            connection.close()
    except Exception as exc:
        result["error"] = type(exc).__name__
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--unit-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Use a fresh output filename; existing evidence is preserved.")
    repo = Path(__file__).resolve().parents[2]
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    root = ET.parse(args.unit_report).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    units = {name: sum(int(s.attrib.get(name, 0)) for s in suites)
             for name in ["tests", "failures", "errors", "skipped"]}
    knowledge = observe_knowledge(DEFAULT_BUNDLE)
    protected = compare_manifest(repo, baseline["protected"])
    preserved = compare_manifest(repo, baseline["preserved_okf_stage3"])
    groups = {prefix: compare_manifest(repo, {k: v for k, v in baseline["protected"].items()
                                           if k.startswith(prefix + "/")})
              for prefix in ["agent", "agent2", "a2a_app"]}
    status = subprocess.check_output(["git", "status", "--porcelain=v1", "--untracked-files=all"],
                                     cwd=repo).decode()
    outside = [line for line in status.splitlines()
               if not (line[3:].startswith("okf_app/") or line[3:] == "okf-spec-prompt.md")]
    service = service_observation()
    report = {"stage": 4, "created_at": datetime.now(timezone.utc).isoformat(),
              "knowledge": knowledge, "unit_tests": units, "protected": protected,
              "agent_groups": groups, "preserved_stage3": preserved,
              "stage3_service": service, "stage3_service_before": baseline["stage3_service"],
              "changes_outside_scope": outside,
              "baseline_sha256": sha256(args.baseline),
              "unit_report_sha256": sha256(args.unit_report)}

    def check(identifier, label, passed, detail):
        return {"id": identifier, "label": label, "passed": bool(passed), "detail": detail}

    concepts = knowledge["concepts"]
    cases = knowledge["cases"]
    unsupported = knowledge["unsupported"]
    access = knowledge["access"]
    report["checks"] = [
        check("bundle", "OKF bundle validation", knowledge.get("validation", {}).get("ezstore_bundle_valid"),
              knowledge.get("validation", {})),
        check("concepts", "Four concepts discovered and read",
              {c["document"] for c in concepts} == set(CONCEPT_FILES) and all(c["passed"] for c in concepts),
              {"concepts_read": len(concepts), "documents": [c["document"] for c in concepts]}),
        check("answers", "Expected knowledge returned", len(cases) == 4 and all(c["passed"] for c in cases),
              {"passed_cases": sum(c["passed"] for c in cases), "total_cases": len(cases),
               "source_grounding_checked": all(c["grounded_in_source"] for c in cases)}),
        check("unsupported", "Unsupported knowledge not fabricated",
              len(unsupported) == len(UNSUPPORTED) and all(c["passed"] for c in unsupported),
              {"refused_cases": sum(c["passed"] for c in unsupported), "total_cases": len(unsupported)}),
        check("readonly", "Consumer remains read-only", knowledge["read_only_passed"],
              {**access, "bundle_hashes_unchanged": knowledge["bundle_before"] == knowledge["bundle_after"],
               "write_requests_refused": sum(c["passed"] for c in knowledge["write_requests"])}),
        check("protected", "Protected project files unchanged", protected["passed"] and not outside,
              {**protected, "changes_outside_scope": outside}),
        check("agents", "First Agent, Second Agent and A2A unchanged", all(g["passed"] for g in groups.values()),
              groups),
        check("stage3", "Stage 3 demo and evidence preserved",
              preserved["passed"] and service.get("pid") == baseline["stage3_service"]["pid"]
              and service.get("http_status") == 200 and service.get("concept_count") == 4,
              {"preserved_files": preserved["files"], "changed_files": preserved["changed"],
               "pid_before": baseline["stage3_service"]["pid"], "pid_after": service.get("pid"),
               "http_status": service.get("http_status")}),
        check("tests", "Relevant tests", units["tests"] > 0 and units["failures"] == units["errors"] == 0, units),
    ]
    report["passed"] = all(c["passed"] for c in report["checks"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(args.output), "passed": report["passed"],
                      "checks": [{"label": c["label"], "passed": c["passed"]} for c in report["checks"]]},
                     indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
