# EZStore OKF Knowledge App

This read-only application represents verified EZStore domain knowledge in an Open Knowledge Format (OKF) Markdown/YAML bundle. It provides background knowledge relevant to Sales & Customer Insight; live customer values and transaction records remain in the Backend API. The consumer is deterministic and does not call Gemini, the Backend, MCP, or the existing agents.

## Bundle and concepts

`bundle/index.md` is the OKF entry point and links to four concepts:

| Document | Knowledge |
|---|---|
| `customer-knowledge.md` | Customer attributes and the `vip`, `standard`, and `new` levels; customer relationships to quotations and orders. |
| `quotation-pricing.md` | Default pricing factors (VIP `0.80`, Standard `0.90`, New `1.00`) and documented price, total, and profit calculations. |
| `quotation-lifecycle.md` | Draft and published states, including restrictions on published quotations. |
| `quotation-order-relationship.md` | An order's nullable `quotation_id`, linked quotations, and standalone orders. |

The validator checks the five required files, YAML frontmatter, a non-empty `type` on every concept, parseability, and internal links. The read-only consumer validates the bundle on each request, locates a relevant concept, and extracts the answer from its Markdown. Unsupported or live-data questions receive no fabricated answer.

## Run locally

Use Python 3.12 and `uv`. Run these commands from `okf_app/`:

```powershell
uv sync --python 3.12
uv run --no-sync python -m okf_knowledge.validator bundle --json
uv run --no-sync pytest -p no:cacheprovider
```

Start the Stage 3 interactive demo on http://127.0.0.1:8020/:

```powershell
uv run --no-sync python -m okf_knowledge.demo --port 8020
```

In a separate terminal, display the saved Stage 4 verification report at http://127.0.0.1:8021/:

```powershell
uv run --no-sync python -m okf_knowledge.verification_dashboard --report artifacts/stage4/verification-20261027T144152Z/report.json --port 8021
```

Both services are already running for the accepted demonstration; use the commands above only when starting them in a new session. The dashboard reads the saved report and derives its PASS/FAIL labels from recorded checks. It does not rerun verification or change the Stage 3 demo.

## Verified results

- **Stage 3:** All four required questions returned answers from the corresponding OKF documents in the interactive demo; 59 tests passed. See [Stage 3 evidence](artifacts/stage3/summary.md).
- **Stage 4:** All nine end-to-end checks passed, including four discoverable concepts, four grounded answers, unsupported-question refusal, read-only access, and protected-file integrity; 72 tests passed. See [Stage 4 evidence](artifacts/stage4/verification-20261027T144152Z/summary.md) and the [saved report](artifacts/stage4/verification-20261027T144152Z/report.json).

The existing First Agent, Second Agent, A2A application, frontend, backend, MCP server, seed data, and Docker Compose files were not modified.
