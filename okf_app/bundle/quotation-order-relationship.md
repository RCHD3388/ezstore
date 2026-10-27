---
type: Reference
title: Quotation-Order Relationship
description: Nullable quotation linkage and standalone orders.
tags: [ezstore, quotations, orders, sales-insight]
sources:
  - id: order-model
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/models/order.go#L16-L19
    title: Nullable quotation reference and customer reference
  - id: quotation-model
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/models/quotation.go#L16-L18
    title: Quotation customer reference
  - id: order-input
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/services/order_service.go#L13-L17
    title: Optional quotation identifier in order input
  - id: sales-insight-linkage
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/agent2/sales_insight_agent/operations.py#L77-L84
    title: Existing Sales Insight quotation-link matching
---
# Quotation-Order Relationship

## Linked orders

An order can reference a quotation through `quotation_id`: a non-null
`order.quotation_id` identifies the associated `quotation.id`. The order model
and input both make this field optional.[^order-model][^order-input]

Both quotations and orders also carry their own `customer_id` reference.
See [Customer Knowledge](customer-knowledge.md).[^quotation-model][^order-model]

## Standalone orders

An order with `quotation_id = null` is a standalone order without an associated
quotation. It does not establish a quotation conversion relationship. Existing
Sales Insight matching considers non-null quotation IDs that match a quotation.
[^order-model][^sales-insight-linkage]

Actual quotation/order links and conversion counts are live Backend/API data.

[^order-model]: Order relationship fields recorded in frontmatter.
[^quotation-model]: Quotation customer field recorded in frontmatter.
[^order-input]: Optional quotation input recorded in frontmatter.
[^sales-insight-linkage]: Existing Sales Insight matching recorded in frontmatter.
