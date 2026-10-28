"""Read-only local dashboard for one saved Customer Overview A2A verification run."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree


def load_view(report_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    checks = report.get("checks")
    if not isinstance(checks, dict) or not checks or not all(isinstance(v, bool) for v in checks.values()):
        raise ValueError("Saved verification checks are missing or invalid.")
    tasks = report.get("sales_a2a_tasks") or []
    card = report.get("sales_agent_card") or {}
    test_summary = None
    junit_path = report_path.with_name("unit-integration.xml")
    if junit_path.is_file():
        try:
            suites = ElementTree.parse(junit_path).getroot()
            test_suites = [suites] if suites.tag == "testsuite" else suites.findall("testsuite")
            test_summary = {
                key: sum(int(suite.get(key, "0")) for suite in test_suites)
                for key in ("tests", "failures", "errors", "skipped")
            }
        except (OSError, ValueError, ElementTree.ParseError):
            pass
    return {
        "created_at": report.get("created_at"),
        "scope": report.get("scope"),
        "protocol": report.get("protocol"),
        "endpoints": report.get("endpoints") or {},
        "checks": checks,
        "passed": all(checks.values()) and not report.get("error"),
        "agent_card": {
            "name": card.get("name"),
            "skills": [skill.get("id") for skill in card.get("skills", [])],
            "interfaces": card.get("supportedInterfaces") or [],
        },
        "customer_overview": report.get("customer_overview") or {},
        "remote_result": report.get("sales_remote_result") or "",
        "a2a_tasks": [
            {"id": task.get("id"), "status": (task.get("status") or {}).get("state"),
             "history": task.get("history") or [], "artifacts": task.get("artifacts") or []}
            for task in tasks
        ],
        "quotation_regression": report.get("quotation_regression") or {},
        "test_summary": test_summary,
        "error": report.get("error"),
    }


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EZStore · A2A Flow Verification</title><style>
:root{font-family:Inter,Segoe UI,Arial,sans-serif;color:#e8f3ff;background:#0b1524}
*{box-sizing:border-box}body{margin:0;padding:0 24px 56px;background:radial-gradient(circle at 75% 0,#163d50 0,transparent 38%),#0b1524}
main{max-width:1180px;margin:auto}.top{display:flex;align-items:center;justify-content:space-between;padding:25px 0;border-bottom:1px solid #ffffff22}
.brand{font-size:14px;letter-spacing:.14em;font-weight:750;color:#69dbca}.eyebrow{color:#91aabc;text-transform:uppercase;letter-spacing:.18em;font-size:12px;font-weight:700}
h1{font-size:clamp(32px,5vw,54px);line-height:1.06;letter-spacing:-.04em;margin:28px 0 10px}p{color:#a9bdce;line-height:1.5}
.hero{display:flex;justify-content:space-between;gap:22px;align-items:end}.badge{border-radius:100px;padding:10px 17px;font-weight:800;letter-spacing:.08em;background:#153e37;color:#6de4ba}
.badge.fail,.fail{background:#502638;color:#ff9daa}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:34px 0 24px}
.node{padding:20px;border:1px solid #426579;background:#13283a;border-radius:18px;min-height:130px}
.node strong{display:block;font-size:19px;margin:10px 0}.node small{color:#91acbf;word-break:break-word}.section{background:#111f30;border:1px solid #324b60;border-radius:20px;padding:22px;margin:18px 0}
.section h2{margin:0 0 16px;font-size:19px}.checks{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}.check{padding:11px 13px;border-radius:10px;background:#163549;color:#d6eafa;font-size:14px}
.check.fail{background:#502638;color:#ffb6bf}.label{font-size:11px;color:#83dccd;text-transform:uppercase;letter-spacing:.14em;font-weight:800}
pre{white-space:pre-wrap;word-break:break-word;background:#081522;border:1px solid #314c60;border-radius:12px;padding:18px;color:#e9f8ff;line-height:1.55;font-size:14px}
.meta{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:#a9bdce}.meta span{word-break:break-word}
@media(max-width:760px){.grid{grid-template-columns:1fr}.hero{display:block}.checks{grid-template-columns:1fr}}
</style></head><body><main>
<div class="top"><div class="brand">EZSTORE / PROTOCOL EVIDENCE</div><div class="eyebrow">Saved run · read only</div></div>
<div class="hero"><div><div class="eyebrow" style="margin-top:30px">Customer Overview extension</div><h1>One request.<br>Real A2A delivery.</h1><p>Every label below is read from a saved verification report. No actions run from this page.</p></div><div id="overall" class="badge">LOADING</div></div>
<div class="grid">
 <div class="node"><div class="label">Coordinator route</div><strong id="route">Loading</strong><small id="agent"></small></div>
 <div class="node"><div class="label">Agent Card discovery</div><strong id="discovery">Loading</strong><small id="skill"></small></div>
 <div class="node"><div class="label">A2A Task</div><strong id="task-status">Loading</strong><small id="task-id"></small></div>
</div>
<div class="section"><div class="label">Coordinator prompt → remote text artifact</div><h2>Customer Overview result</h2><p id="prompt"></p><pre id="result">Loading saved result…</pre></div>
<div class="section"><h2>Safety and regression</h2><div id="checks" class="checks"></div></div>
<div class="section"><h2>Test summary</h2><div id="test-summary" class="meta"></div></div>
</main><script>
const put=(id,text)=>document.getElementById(id).textContent=String(text??'—');
fetch('/api/report').then(r=>{if(!r.ok)throw Error('Saved report unavailable');return r.json()}).then(d=>{
  const badge=document.getElementById('overall');badge.textContent=d.passed?'ALL CHECKS PASS':'CHECKS FAILED';badge.classList.toggle('fail',!d.passed);
  put('route',d.customer_overview.route);put('agent',d.agent_card.name||'No agent recorded');
  put('discovery',d.checks.sales_card_discovery?'PASS':'FAIL');
  put('skill',(d.agent_card.skills||[]).join(', ')||'No skill recorded');
  const task=d.a2a_tasks[0]||{};put('task-status',task.status||'No task recorded');put('task-id',task.id||'No task ID recorded');
  const labels={
    sales_a2a_message_exchange:'A2A message exchange',customer_overview_result:'Customer Overview result',
    unsupported_refused:'Unsupported request refused',write_and_off_topic_refused:'Write and off-topic refused',
    quotation_regression:'Quotation A2A regression',no_direct_backend_mcp_fallback:'No backend/MCP fallback'
  };
  const checks=document.getElementById('checks');Object.entries(labels).forEach(([name,label])=>{
    const passed=d.checks[name]===true;
    const row=document.createElement('div');row.className='check'+(passed?'':' fail');row.textContent=(passed?'PASS':'FAIL')+' · '+label;checks.append(row);
  });
  put('prompt',d.customer_overview.prompt);put('result',d.remote_result||'No remote result recorded.');
  const tests=d.test_summary;
  put('test-summary',tests?`${tests.tests} tests · ${tests.failures} failures · ${tests.errors} errors · ${tests.skipped} skipped`:'No saved test report available.');
}).catch(e=>{const badge=document.getElementById('overall');badge.textContent='REPORT UNAVAILABLE';badge.classList.add('fail');put('result',e.message)});
</script></body></html>"""


def create_server(report_path: Path, *, host="127.0.0.1", port=8014) -> ThreadingHTTPServer:
    report_path = Path(report_path).resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return None

        def respond(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                return self.respond(200, HTML.encode(), "text/html; charset=utf-8")
            if self.path == "/api/report":
                try:
                    view = load_view(report_path)
                except (OSError, ValueError, json.JSONDecodeError):
                    return self.respond(503, b'{"error":"Saved verification report unavailable"}', "application/json")
                return self.respond(200, json.dumps(view, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            return self.respond(404, b"Not found", "text/plain")

        def do_POST(self):
            return self.respond(405, b"Read-only dashboard", "text/plain")

        do_PUT = do_PATCH = do_DELETE = do_POST

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8014)
    args = parser.parse_args()
    create_server(args.report, port=args.port).serve_forever()
