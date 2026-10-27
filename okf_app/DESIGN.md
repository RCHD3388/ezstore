# Stage 1 - OKF preflight and knowledge design

Status: proposed design for user acceptance. No bundle, validator, or consumer
has been implemented. No live EZStore API, database, or LLM request was made.

## Format basis

Checked on 2026-10-27 against the official GoogleCloudPlatform
[Open Knowledge Format specification](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md),
currently v0.2. Relevant sections: 4 (concepts), 5.1 (sources), 6 (links),
8 (reserved index files), 11 (conformance), and 12 (version declaration).

Concepts use UTF-8 Markdown with YAML frontmatter and a non-empty string `type`.
Use `type: Reference` for all four concepts, with `title`, `description`, `tags`,
and source provenance. Preserve unknown optional fields/types when parsing.
The reserved root `index.md` uses only the allowed `okf_version: "0.2"`
frontmatter and a heading/list of links. It is not a fifth typed concept.

Required filenames and fully resolving internal links are EZStore project checks.
They are stricter than general OKF conformance, which tolerates missing indexes
and broken links. The future validator will distinguish structural conformance
from these project checks.

## Proposed bundle (Stage 2)

```text
okf_app/
  DESIGN.md
  bundle/
    index.md
    customer-knowledge.md
    quotation-pricing.md
    quotation-lifecycle.md
    quotation-order-relationship.md
```

The four concept files will be siblings. `index.md` links to each using its exact
relative filename, with a short description. Relevant concepts may cross-link
to one another with standard Markdown links.

Root-index frontmatter design:

```yaml
---
okf_version: "0.2"
---
```

Example concept-frontmatter design (not an implemented concept):

```yaml
---
type: Reference
title: Quotation Pricing
description: EZStore default pricing factors and quotation calculations.
tags: [ezstore, quotations, pricing]
sources:
  - id: customer-model
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/models/customer.go#L25-L36
    title: Customer-level default pricing factors
---
```

Source IDs will connect body claims to their provenance using Markdown footnotes.
No human-verification attestation, timestamps, or source usage figures will be
invented. Domain quotation `draft`/`published` values belong in the body; they
are not OKF document-lifecycle metadata.

## Verified content and project sources

Sources below were inspected in the local checkout at Git revision
`32f11e2226bc8584115f7c50c0b1b461932456eb`. Source paths and line numbers identify
the evidence for each planned statement. Concept provenance will link to that
repository revision rather than copying source files or transaction records.

### customer-knowledge.md

- Levels are `vip`, `standard`, and `new`.
- Relevant schema attributes: `id`, `name`, `tax_id`, `contact_name`,
  `contact_phone`, `contact_email`, `address`, `level`, and `credit_score`.
- Credit score is an integer constrained to 0-100.
- Quotations and orders reference their customer through `customer_id`.

Evidence:

- [Customer model](../backend/models/customer.go), lines 10-22.
- [Customer validation](../backend/services/customer_service.go), lines 71-85.
- [Quotation customer relationship](../backend/models/quotation.go), lines 16-18.
- [Order customer relationship](../backend/models/order.go), lines 16-19.
- [README domain schema](../README.md), lines 414-433.

The document describes attribute meanings and constraints, not any customer's
current level, score, contact information, or sales activity.

### quotation-pricing.md

- Default factors: VIP `0.80`, Standard `0.90`, New `1.00`.
- A quotation's factor adjusts product list prices and can be supplied per quote.
- `unit_price = list_price * pricing_factor`.
- `subtotal = unit_price * quantity`; `total_price = sum(subtotal)`.
- `profit_amount = sum((unit_price - product_cost) * quantity)`.
- `profit_rate = profit_amount / total_price`, with zero used when total is zero.

Evidence:

- [Default factor helper](../backend/models/customer.go), lines 25-36.
- [Documented pricing rules](../README.md), lines 229-247.
- [Swagger pricing description](../backend/docs/docs.go), line 462 and line 783.
- [Item pricing](../backend/services/quotation_service.go), lines 183-211.
- [Totals and profit calculations](../backend/services/quotation_service.go), lines 214-231.

Defaults are reference values, not a claim that every VIP quotation must use
`0.80`. Creation accepts a required `pricing_factor` input and assigns it directly
(service lines 13-18 and 49-59); do not claim the Backend automatically substitutes
a default for an omitted factor. Do not invent rounding, tax, or profitability
policies.

### quotation-lifecycle.md

- Newly created quotations are `draft`.
- Draft quotations may be edited or deleted through the documented operations.
- Publishing changes a draft to `published` and is documented as irreversible.
- Published quotations cannot be edited, deleted, or published again.

Evidence:

- [Quotation creation/update](../backend/services/quotation_service.go), lines 49-108.
- [Publish/delete guards](../backend/services/quotation_service.go), lines 113-140.
- [Swagger update/delete descriptions](../backend/docs/docs.go), lines 861 and 914.
- [Swagger irreversible publication](../backend/docs/docs.go), line 996.
- [README publication behavior](../README.md), lines 249-252 and 467.

Irreversibility describes the supported application/API lifecycle. It does not
claim that privileged out-of-band database operations are impossible. No
publication or modification will be performed by this OKF application.

### quotation-order-relationship.md

- A non-null `order.quotation_id` identifies its associated quotation's `id`.
- The order field is nullable; a null value represents a standalone order.
- Both entities independently carry `customer_id`.
- A standalone order does not establish a quotation conversion relationship.

Evidence:

- [Nullable order relationship](../backend/models/order.go), lines 16-19.
- [Order input and creation](../backend/services/order_service.go), lines 13-17 and 50-59.
- [Swagger optional relationship](../backend/docs/docs.go), line 295.
- [README entity schema](../README.md), lines 430-433.
- [Existing Sales Insight relationship handling](../agent2/sales_insight_agent/operations.py),
  lines 77-84 and 118-145 (read-only reference).

The API prose describes optionally linking a published quotation, but the order
service does not validate publication status when assigning `quotation_id`.
Therefore do not assert a published-only link constraint. The model does not
establish a unique one-order-per-quotation constraint; do not invent one. Keep the
concept focused on nullable linkage and avoid promises of automatic conversion
or line-item copying.

## Stable knowledge versus live data

| Static OKF knowledge | Live Backend/API information excluded from the bundle |
|---|---|
| Customer field definitions and allowed levels | Actual customer identities, contact details, levels, and credit scores |
| Default factor mapping and pricing formulas | A particular quotation's applied factor, prices, items, or profit |
| Quotation status meanings and publication restrictions | Current record statuses, IDs/numbers, timestamps, and transaction histories |
| `customer_id` and nullable `quotation_id` relationship semantics | Actual linked orders, quotation/order counts, totals, and conversion metrics |

The bundle explains how to interpret Sales & Customer Insight data. It does not
replace the existing Agent's read-only Backend queries. Schema/default constants
are allowed; current records and computed business figures are not static facts.

## Later-stage boundary

Stage 2 will create only the approved five bundle documents, a small parser/
validator, and its tests inside `okf_app/`. The validator will check required files,
YAML/frontmatter, concept types, project links, and successful parsing, with the
root-index exception above.

Stage 3 can use deterministic concept discovery and section/table extraction;
answers must be loaded from bundle content, not factual strings in code. No LLM
is needed for the proposed demonstration. If one becomes necessary, the required
model is `gemini-3.6-flash`. Unsupported or live-data questions should be identified
as outside the bundle's knowledge rather than answered with invented facts.

All implementation stays in `okf_app/`. Existing agents, A2A files, application
components, Compose files, and seed data remain protected. Await Stage 1 acceptance
before implementing the bundle or executing later-stage tests/demonstrations.
