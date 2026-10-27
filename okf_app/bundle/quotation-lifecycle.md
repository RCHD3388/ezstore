---
type: Reference
title: Quotation Lifecycle
description: Draft/published states and publication restrictions.
tags: [ezstore, quotations, lifecycle]
sources:
  - id: quotation-service
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/services/quotation_service.go#L49-L140
    title: Creation, modification, publication, and deletion guards
  - id: publication-docs
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/docs/docs.go#L994-L1006
    title: Documented irreversible publication
---
# Quotation Lifecycle

## Draft and published

| Status | Meaning and supported operations |
|---|---|
| `draft` | Initial state of a newly created quotation; it may be edited, deleted, or published. |
| `published` | Published quotation; it cannot be modified, deleted, or published again. |

The quotation service enforces the publication guards.[^quotation-service]

## Publishing

Publishing changes `draft` to `published`. The API documentation defines this
operation as irreversible; the supported application lifecycle has no unpublish
operation.[^publication-docs]

This describes application/API behavior. The current status of a particular
quotation must be read from the Backend/API.

See [Quotation Pricing](quotation-pricing.md) for calculation definitions.

[^quotation-service]: Quotation lifecycle implementation recorded in frontmatter.
[^publication-docs]: Publication API documentation recorded in frontmatter.
