# Quotation evaluation datasets

`basic-dataset.json` keeps the scaffold's no-argument `agents-cli eval run`
entry point working with a single read-only quotation query. The two required
acceptance datasets below contain the full nine cases.

`quotation-actions.json` contains the six required operations. It creates three
quotation copies and an order when all actions succeed. Use the seeded backend.

`quotation-guardrails.json` contains two refusals and one continuation case.
The SSE generator in agents-cli 1.11 seeds prior `agent_data.turns` into a new
session and executes only the final user message. The clarification turn therefore
includes the actual clarification text. ADK rejects client-supplied state actions,
so the classifier receives the prior unresolved request from ordinary history
when session state is absent. It tests continuing a pending query, rather than
treating the bare quotation number as a fresh operation. The live two-request clarification
flow was separately verified in Stages 4.2 and 4.3.

ADK 2.13's `/app-info` endpoint supports only an `LlmAgent` root and returns 400
for the required Workflow root. The CLI warns and uses its metadata fallback;
the actual Workflow events and MCP calls remain in the trace.

From `agent/`, run each dataset sequentially:

```powershell
uv sync --group dev --extra eval
agents-cli eval run --dataset tests/eval/datasets/quotation-guardrails.json --config tests/eval/eval_config.yaml --concurrency 1 --qps 0.05 --output artifacts/grade_results/guardrails
agents-cli eval run --dataset tests/eval/datasets/quotation-actions.json --config tests/eval/eval_config.yaml --concurrency 1 --qps 0.05 --output artifacts/grade_results/actions
```

To use the Compose Agent, append
`--url http://localhost:3000/agent-api --app-name quotation_agent`.

The selected metrics are exactly `custom_response_quality`, `link_present`,
`refusal_or_action`, and `agent_turn_count`. Both LLM judges consume their YAML
`prompt_template` through local Python adapters, using the root `.env` credentials
and `AGENT_MODEL` (default `gemini-3.8-flash`). Judge requests are serialized with
a 30-second gap; the CLI spaces inference cases by 20 seconds by default. Model
requests retry 429/503/504 up to three attempts with exponential backoff
(30-second initial delay, 120-second cap); persistent upstream errors remain
metric errors. The link
metric exempts only case IDs starting with `off_topic` and rejects Markdown links.

## AI Studio evaluation compatibility

The installed aiplatform 2.6 SDK eagerly initializes GCS/BigQuery clients even
for in-memory evaluation data. In addition, the independent config expresses
`refusal_or_action` as an `LLMMetric`, whose default transport is Vertex.

`agent/agents-cli-extension.yaml` uses the official project extension mechanism
for `eval run` and `eval grade`. With an AI Studio key, the wrapper runs the
installed, unmodified CLI with a process-local compatibility module:

- GCS/BigQuery clients authenticate lazily, only if a cloud dataset is used.
- Original custom `prompt_template` rubrics execute through `google-genai` with
  the required model. They retain their text, model settings and sampling count.
- Existing Python metric functions, SDK aggregation, JSON/HTML output and the
  independent scoring weights/post-checks remain in use. Judge failures remain
  errors, never invented scores.
- Inference is sequential by default and LLM grading requests are serialized
  with a 30-second gap. Runtime logs are in `agent/artifacts/eval_runs/`.

The module activates only in the wrapped CLI, not in the Agent subprocess, and
does not edit installed packages or require an ADC credential for local data.
Vertex users retain the built-in CLI transport. Set
`AGENTS_CLI_DISABLE_OVERRIDES=1` to explicitly invoke the unmodified CLI.

The independent `scripts/grading/grade_agent.py`, its config, rubrics and suite
are unchanged. Its actions group reseeds the test database before checking new
copies and orders. From the repository root:

```powershell
uv run --no-sync --project agent --env-file .env python scripts/grading/grade_agent.py --suite scripts/grading/student-suite.json
```

The grader's warning about no credential in `agent/.env` is a file-only
preflight heuristic; the command above correctly inherits the root `.env` key.
