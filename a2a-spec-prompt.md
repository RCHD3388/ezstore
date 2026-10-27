# EZStore A2A Application Specification

## Assignment and revised acceptance scope

> Complete an A2A application using the A2A protocol.

The required demonstration is:

```text
User -> EZStore A2A Coordinator -> A2A -> quotation_agent
```

The Coordinator and quotation specialist run as independent services. Discovery
uses the specialist's Agent Card, and delegation uses real A2A messages. Direct
Python business calls, Backend REST, MCP, database access, or shared memory from
the Coordinator do not satisfy this requirement and must not replace A2A.

This scope revision supersedes the former requirement for two remote specialists.
`customer_insight_only` and `combined_cross_agent` are excluded from required
acceptance. Existing Sales Insight experiments and prior evidence may remain,
but are not required, are not claimed as accepted, and must not be debugged or
rerun for this quotation-only acceptance. Previously passed results are preserved.

## Protection rules

All new implementation belongs under `a2a_app/`. This specification is the only
permitted change outside that directory. Do not modify:

- `agent/` or `agent2/`, including their completed evaluation artifacts;
- `frontend/`, `backend/`, or `mcp_server/`;
- `scripts/seed-test-data.sql`;
- existing Docker Compose files or other completed First/Second Agent files.

Existing agents may be started or exposed using supported runtime configuration
without source changes. Do not reseed or mutate business data. Do not commit
without explicit authorization.

## Required application behavior

ADK app name: `ezstore_a2a_coordinator`.

1. Retrieve the independent `quotation_agent` Agent Card and use its advertised
   A2A interface.
2. Deterministically route a quotation lookup such as
   `Show me quotation QT-20260330-001.` to `quotation_agent` through A2A.
3. Return the specialist's factual quotation result, including its system link.
4. Refuse business writes (including creation, changes, deletion, duplication,
   publication, and conversion) before contacting a specialist.
5. Politely refuse off-topic requests.
6. Report a named remote-agent/A2A error if the specialist is unavailable; never
   fall back to direct Backend or MCP access.

The Coordinator does not call Gemini for classification or response composition.
Business lookup logic stays in the unchanged quotation specialist. The specialist
may use its existing model, MCP, and Backend integrations internally.

```text
User request
    |
Deterministic router
    |-- Quotation lookup -> Agent Card discovery -> A2A -> quotation_agent
    |-- Write request -> refuse
    `-- Off-topic -> refuse
    |
Final response
```

## Runtime and configuration

Use Python 3.12, uv, and the existing compatible ADK/A2A SDK APIs. Keep dependencies,
source, tests, and evidence under `a2a_app/`, including `pyproject.toml` and
`uv.lock`. Use the installed google-agents-cli tools/skills and official SDK/API
documentation when needed; do not assume constructors or protocol endpoints.

Required Coordinator configuration:

```text
QUOTATION_AGENT_CARD_URL=http://localhost:8011/a2a/quotation_agent/.well-known/agent-card.json
APP_URL=http://127.0.0.1:8013
A2A_TIMEOUT_SECONDS=180
```

The card's advertised interface determines the A2A service endpoint. Credentials
and `AGENT_MODEL` are configured for the existing specialist as needed. The
Coordinator itself needs no Gemini API access. Never print or commit credentials.
`SALES_INSIGHT_AGENT_CARD_URL` is not required for the revised acceptance.

## Tests and evidence

Relevant automated checks cover:

- quotation routing and A2A delegation;
- preservation of the remote result;
- write refusal without a remote call;
- off-topic refusal without a remote call;
- named remote-unavailable errors without a direct fallback;
- supported A2A Message/Task response extraction.

Save concise new evidence under `a2a_app/artifacts/`. Preserve earlier artifacts;
do not overwrite previous results or label unsuccessful experiments as passes.

## Staged acceptance

Stop after each stage for user verification. Explain what was completed, what to
verify, and the expected result. A scope revision does not automatically accept a
stage or authorize proceeding to the next stage.

### Stage 1 - A2A preflight

Inspect the existing quotation runtime and current compatible APIs. Demonstrate
an Agent Card identifying `quotation_agent` with a usable A2A interface, without
modifying protected source. Prior accepted preflight evidence remains valid.

### Stage 2 - Coordinator implementation

Implement deterministic routing, Agent Card discovery, A2A quotation delegation,
write/off-topic refusal, and remote failure handling entirely under `a2a_app/`.
Run relevant unit tests and confirm protected files are unchanged.

### Stage 3 - Local A2A acceptance (current checkpoint)

Run the Coordinator and independent quotation specialist. Verify:

| Check | Expected result |
|---|---|
| Quotation Agent Card discovery | Card identifies `quotation_agent` and advertises its usable A2A interface |
| One real quotation request | Coordinator delegates `Show me quotation QT-20260330-001.` through A2A |
| Quotation response | Specialist result returns through A2A and is shown by the Coordinator, including its quotation system link |
| Write refusal | Existing guard refuses without a remote/business write |
| Off-topic refusal | Existing guard refuses without remote delegation |

Record the actual card, protocol response, and displayed result. Unit tests may
support guardrail checks. No Sales Insight or combined request is required or
permitted for this checkpoint. Do not repeatedly retry Gemini failures. Report
Stage 3 honestly and stop for user verification; do not proceed to Stage 4.

### Stage 4 - Protocol verification (requires separate authorization)

Run automated protocol checks for the required quotation-only path. Report a
concise table of case, remote agent, protocol, result, and pass/fail. Verify Card
discovery, A2A message exchange, no direct fallback, and protected-file integrity.
Confirm that the read-only application has not modified Backend data. Save
verification evidence under `a2a_app/artifacts/`.

### Stage 5 - Documentation and final check (requires separate authorization)

Complete `a2a_app/README.md` with purpose, the two-service architecture, roles,
Agent Card/A2A flow, environment configuration, startup/test commands, and a
quotation-only demonstration. State that First/Second Agent sources were not
modified. Run `git status` and `git diff`, list new A2A files, and confirm all work
is confined to `a2a_app/` and `a2a-spec-prompt.md`. Stop without committing.

## Final success criteria

- A working Coordinator and independently served quotation specialist participate.
- Agent Card discovery and real A2A message exchange are demonstrated.
- A quotation result returns successfully through A2A.
- Existing write/off-topic guardrails pass, with no direct Backend/MCP fallback.
- Relevant tests, later authorized verification, and documentation are complete.
- Protected project files and business data remain unchanged.
