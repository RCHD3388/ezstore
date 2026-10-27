# EZStore OKF Application Specification

Build a small **Open Knowledge Format (OKF)** application for the existing EZStore project.

The goal is to demonstrate that structured EZStore domain knowledge can be represented as an OKF knowledge bundle, validated, and consumed by an application related to the existing **Sales & Customer Insight Agent**.

Use `gemini-3.6-flash` if an LLM is required.

---

## 0. Scope and Protection Rules

All new OKF implementation must stay inside:

```text
okf_app/
```

The specification file may be:

```text
okf-spec-prompt.md
```

Strictly do **not modify**:

- `agent/`
- `agent2/`
- `a2a_app/`
- `frontend/`
- `backend/`
- `mcp_server/`
- `scripts/seed-test-data.sql`
- `docker-compose.yml`
- `docker-compose.build.yml`
- any completed First Agent, Second Agent, or A2A files

The existing `sales_insight_agent` may be used only as reference or through an external adapter/consumer inside `okf_app/`. Do not modify its source code.

Do not put API keys in source code, logs, artifacts, or Git.

---

# Stage 1 — OKF Preflight and Knowledge Design

Before implementation:

1. Check the current official OKF specification and use its required Markdown/YAML structure.
2. Inspect the existing EZStore documentation/API definitions to confirm every knowledge statement.
3. Do not invent new EZStore business rules.
4. Separate:
   - **stable domain knowledge** → OKF
   - **live transaction records** → Backend/API, not static OKF knowledge

Create the following OKF knowledge bundle design:

```text
okf_app/
└── bundle/
    ├── index.md
    ├── customer-knowledge.md
    ├── quotation-pricing.md
    ├── quotation-lifecycle.md
    └── quotation-order-relationship.md
```

The four knowledge concepts should cover only verified EZStore knowledge:

### Customer Knowledge
- customer levels: `vip`, `standard`, `new`
- relevant customer attributes
- relationship of customers to quotations and orders

### Quotation Pricing
- default pricing factors:
  - VIP = `0.80`
  - Standard = `0.90`
  - New = `1.00`
- pricing-factor purpose
- quotation price/total/profit concepts supported by EZStore documentation

### Quotation Lifecycle
- `draft`
- `published`
- published quotations cannot be modified or deleted
- publishing is irreversible if supported by the project documentation

### Quotation–Order Relationship
- quotation/order relationship through `quotation_id`
- an order may be linked to a quotation or exist independently if supported by the project data/model

`index.md` should act as the bundle entry point and link to the four concepts.

Use proper YAML frontmatter for OKF documents. At minimum, every concept must contain a valid non-empty `type`.

Stop after Stage 1 and report the proposed knowledge structure and verified sources. Do not proceed until accepted.

---

# Stage 2 — Build the OKF Knowledge Bundle

Create the bundle entirely inside `okf_app/bundle/`.

Requirements:

- Markdown documents with valid YAML frontmatter
- non-empty `type` on each OKF concept
- concise human-readable Markdown body
- internal links from `index.md`
- no invented business rules
- no API keys or secrets
- no unnecessary copy of live database records

Keep the knowledge concise and focused on the four approved concepts.

Also create a small OKF validator inside `okf_app/` that checks:

1. required Markdown files exist
2. YAML frontmatter is valid
3. `type` exists and is non-empty
4. internal links resolve
5. bundle can be parsed successfully

Add unit tests for these checks.

Stop after Stage 2 and report:
- created files
- validation result
- unit test result

Do not proceed until accepted.

---

# Stage 3 — OKF Consumer Demonstration

Build a small **read-only OKF consumer/adapter** inside `okf_app/`.

It must:

1. load the OKF bundle
2. locate relevant concepts
3. return the relevant knowledge to the application
4. never modify EZStore data
5. never modify `agent2/`

Demonstrate at least these knowledge requests:

1. What is the default pricing factor for a VIP customer?
2. What is the difference between a draft and published quotation?
3. Can a published quotation be modified?
4. How can a quotation relate to an order?

The answers must come from the OKF bundle, not from hard-coded answer strings.

If an LLM is used for natural-language presentation, use:

```text
AGENT_MODEL=gemini-3.6-flash
```

The factual content must still be grounded in the loaded OKF documents.

Stop after Stage 3 and show a concise result table for all demonstration cases.

---

# Stage 4 — Verification

Verify the OKF application end-to-end.

Required checks:

- OKF bundle validates successfully
- all four knowledge concepts can be discovered/read
- expected knowledge is returned correctly
- unsupported knowledge is not fabricated
- OKF consumer is read-only
- no protected project files were modified
- existing First Agent, Second Agent, and A2A implementation remain unchanged

Run all relevant tests and save concise verification evidence under:

```text
okf_app/artifacts/
```

Stop after Stage 4 and report PASS/FAIL for each verification item.

Do not proceed until accepted.

---

# Stage 5 — Documentation and Final Check

Update only:

```text
okf_app/README.md
```

Document briefly:

- purpose of the OKF application
- OKF bundle structure
- four knowledge concepts
- how validation works
- how the consumer uses the bundle
- how to run the tests/demo
- Stage 3 and Stage 4 results
- statement that existing agents and protected project components were not modified

Finally run:

```text
git status
git diff --check
```

Confirm that all OKF work is confined to:

```text
okf_app/
okf-spec-prompt.md
```

Do not commit automatically.

Stop after Stage 5 and report the final result.