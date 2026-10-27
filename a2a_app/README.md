# EZStore A2A Coordinator

This application fulfills the assignment **"Complete an A2A application using the
A2A protocol"** through a read-only quotation lookup. The accepted architecture is:

```text
User -> EZStore A2A Coordinator -> A2A -> quotation_agent
```

The Coordinator (`ezstore_a2a_coordinator`) and the existing quotation specialist
(`quotation_agent`) run as independent services. The Coordinator deterministically
routes quotation requests, refuses business writes and off-topic requests, and
returns the specialist's result. It uses no LLM for classification or composition.
Sales Insight and combined-request experiments are outside the accepted scope.

## Architecture and protocol

```text
User / ADK web UI
        |
        v
Coordinator :8013
  deterministic router
        |
        | Agent Card discovery + A2A JSON-RPC 1.0
        v
quotation_agent :8011
  existing quotation Workflow
        |
        | existing internal MCP integration
        v
MCP Server :8010 -> existing Backend :8080 -> database
```

1. The Coordinator retrieves the quotation Agent Card with the official A2A SDK's
   `A2ACardResolver`. The card identifies `quotation_agent` and advertises its
   supported interface, capabilities, and skills.
2. The SDK client uses the advertised JSON-RPC interface to send an A2A
   `SendMessageRequest`. Quotation business logic runs in the remote specialist.
3. The Coordinator extracts the remote text from supported A2A Message/Task forms
   and exposes it through its `respond` Workflow node.
4. A remote failure returns an error naming the unavailable agent. There is no
   direct Backend, MCP, database, or imported-specialist fallback in the
   Coordinator's delegated business path.

| Surface | Local URL |
|---|---|
| Quotation Agent Card | http://127.0.0.1:8011/a2a/quotation_agent/.well-known/agent-card.json |
| Quotation A2A interface | http://127.0.0.1:8011/a2a/quotation_agent |
| Coordinator ADK web UI | http://127.0.0.1:8013/dev-ui/ |
| Coordinator Agent Card | http://127.0.0.1:8013/a2a/ezstore_a2a_coordinator/.well-known/agent-card.json |

Coordinator-to-specialist communication uses A2A. The specialist's own existing
MCP and Backend integrations supply the quotation data.

## Configuration

| Variable | Used by | Purpose |
|---|---|---|
| `QUOTATION_AGENT_CARD_URL` | Coordinator | Full quotation Agent Card URL shown above |
| `APP_URL` | Each local service | Its advertised origin: port 8011 for the specialist, 8013 for the Coordinator |
| `A2A_TIMEOUT_SECONDS` | Coordinator | Remote request timeout; default 180 seconds |
| `GEMINI_API_KEY` | Existing quotation specialist | AI Studio credential, supplied privately through the project root `.env` |
| `AGENT_MODEL` | Existing quotation specialist | Existing working model configuration |
| `MCP_URL` | Existing quotation specialist | Existing local MCP endpoint, normally `http://localhost:8010/mcp` |

The Coordinator requires no Gemini credential or model access. Never commit real
keys. `.env.example` contains placeholders; any Sales Insight settings there are
optional historical settings and are not needed for this accepted architecture.
Process environment variables take precedence over dotenv files. Use the full
Agent Card URL, including `/a2a/quotation_agent/`, when overriding older local settings.

## Local startup (PowerShell)

Prerequisites: Python 3.12, uv, the installed google-agents-cli, and the existing
quotation-agent environment. The project uses ADK 2.10+ and A2A SDK 1.x, pinned by
`uv.lock`. Reuse services already listening on ports 8011 and 8013 rather than
launching duplicate listeners.

From the repository root, ensure the existing data services are running:

```powershell
docker compose up -d db backend mcp-server
```

Use the existing database as-is. The frontend on port 3000 is needed to open the
returned system links; reuse its running service or start it with the existing
Compose configuration. No seed/reset step is part of this demonstration.

**Terminal 1 - quotation specialist:** from the repository root, run:

```powershell
Set-Location agent
# Load the current private dotenv credential rather than stale inherited keys.
Remove-Item Env:GEMINI_API_KEY, Env:GOOGLE_API_KEY -ErrorAction SilentlyContinue
$env:GOOGLE_GENAI_USE_VERTEXAI = 'false'
$env:GOOGLE_GENAI_USE_ENTERPRISE = 'FALSE'
$env:APP_URL = 'http://127.0.0.1:8011'
$env:PYTHONDONTWRITEBYTECODE = '1'
uv run --no-sync uvicorn quotation_agent.fast_api_app:app --host 127.0.0.1 --port 8011
```

The unchanged specialist reads `agent/.env` and the repository root `.env` when
values are absent from its process environment. Keep its existing model settings.
The command reuses its existing environment and does not synchronize or edit its
source/dependencies.

**Terminal 2 - Coordinator:** from the repository root, run:

```powershell
Set-Location a2a_app
uv sync --frozen
$env:QUOTATION_AGENT_CARD_URL = 'http://127.0.0.1:8011/a2a/quotation_agent/.well-known/agent-card.json'
$env:APP_URL = 'http://127.0.0.1:8013'
uv run --no-sync uvicorn ezstore_a2a_coordinator.fast_api_app:app --host 127.0.0.1 --port 8013
```

Open the Coordinator's ADK web UI, select `ezstore_a2a_coordinator`, create a
session, and send:

```text
Show me quotation QT-20260330-001.
```

Expect a quotation result supplied by the independent specialist over A2A,
including the quotation number, item details, and a plain-text system link.
Returned values reflect the current Backend data. The existing remote output
also includes intent JSON before its business text; that formatting is preserved.

To inspect the specialist's discovery document without invoking a business action:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8011/a2a/quotation_agent/.well-known/agent-card.json'
```

## Tests and verification commands

Run the following from `a2a_app/`. The commands are for an intentional new run;
accepted evidence listed below is already saved and does not need to be replayed.

**Relevant unit tests:** these exercise routing, result handling, refusals, and
failure behavior without calling Gemini or a live specialist. The two no-fallback
tests intercept actual transport HTTP calls and inject discovery/message errors.

```powershell
$unitTests = @(
  'tests/unit/test_quotation_no_fallback.py'
  'tests/unit/test_a2a_transport.py'
  'tests/unit/test_coordinator.py::test_quotation_only_delegates_via_quotation_specialist'
  'tests/unit/test_coordinator.py::test_reject_write_request_without_remote_calls'
  'tests/unit/test_coordinator.py::test_off_topic_without_remote_calls'
  'tests/unit/test_coordinator.py::test_remote_agent_unavailable_has_named_a2a_error_and_no_fallback'
  'tests/unit/test_coordinator.py::test_coordinator_has_no_backend_or_mcp_business_client_imports'
)
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$runDir = "artifacts/stage4/quotation-$stamp"
uv run --no-sync pytest -p no:cacheprovider @unitTests --junitxml="$runDir/unit-tests.xml"
```

**Stage 3 live acceptance:** requires both local services and the existing
Backend/MCP stack. It sends one quotation lookup, verifies the A2A Task/result,
then checks off-topic and write refusals without additional specialist Tasks.

```powershell
$env:PYTHONPATH = (Get-Location).Path
$env:QUOTATION_AGENT_CARD_URL = 'http://127.0.0.1:8011/a2a/quotation_agent/.well-known/agent-card.json'
uv run --no-sync python tests/acceptance/quotation_stage3.py
```

**Stage 4 protocol verification:** after the unit-test command succeeds, use its
new `$runDir` and JUnit report. This sends one new quotation lookup, records the
Agent Card and completed A2A Task, matches the Coordinator reply to the remote
result, audits the Coordinator import path, and checks source/evidence integrity.
Docker access is needed for read-only database snapshots before and after the
lookup. The verifier hashes PostgreSQL data and sequence values; it never restores
or executes the dump. It does not perform business lookup through the database.

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --no-sync python tests/acceptance/quotation_stage4.py --output $runDir --unit-report "$runDir/unit-tests.xml"
```

Both live scripts have no request retry loop. Keep earlier evidence, use a fresh
output directory for verification, and stop to inspect a service failure rather
than repeatedly submitting the same request.

## Accepted Stage 3 and Stage 4 results

Both stages were verified and accepted by the user under the revised
[quotation-only specification](../a2a-spec-prompt.md).

| Stage | Recorded verification | Result |
|---|---|---|
| Stage 3 | 15 relevant unit tests; Agent Card discovery; one completed quotation A2A Task; matching returned quotation result; off-topic/write refusal without extra Tasks | PASS |
| Stage 4 | 12 relevant unit tests; fresh Agent Card discovery and one completed A2A quotation Task; matching returned result; source audit and two intercepted no-fallback failure cases | PASS |
| Stage 4 integrity | All six business tables and sequence values matched before/after; 145 protected tracked files and both prior evidence files matched their hashes | PASS |

The observed quotation was `QT-20260330-001`, total `6175`, with item details and
system link http://localhost:3000/quotations/12. Completed Task IDs:

- Stage 3: `426a169f-d0d2-4bf4-8890-49a1378d10da`.
- Stage 4: `df46f940-fb40-4cc7-848b-ae7de1668586`.

Evidence:

- [Stage 3 raw evidence](artifacts/stage3/quotation-only-20261027T123552Z.json).
- [Stage 4 result table](artifacts/stage4/quotation-20261027T125412Z/summary.md).
- [Stage 4 raw protocol/integrity evidence](artifacts/stage4/quotation-20261027T125412Z/verification.json).
- [Stage 4 JUnit report](artifacts/stage4/quotation-20261027T125217Z/unit-tests.xml).

## Project protection

This A2A work did not modify `agent/`, `agent2/`, `frontend/`, `backend/`,
`mcp_server/`, `scripts/seed-test-data.sql`, `docker-compose.yml`, or
`docker-compose.build.yml`. The original First and Second Agent implementations
remain unchanged. A2A additions/changes are confined to `a2a_app/` and
`a2a-spec-prompt.md`. No automatic commit is performed.
