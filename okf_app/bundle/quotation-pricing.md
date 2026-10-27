---
type: Reference
title: Quotation Pricing
description: Default pricing factors and quotation calculations.
tags: [ezstore, quotations, pricing]
sources:
  - id: factor-defaults
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/models/customer.go#L25-L36
    title: Customer-level default pricing factors
  - id: pricing-input
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/services/quotation_service.go#L13-L18
    title: Explicit quotation pricing-factor input
  - id: pricing-rules
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/services/quotation_service.go#L183-L231
    title: Item pricing, totals, and profit calculation
  - id: pricing-docs
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/README.md#L229-L247
    title: Documented pricing rules and per-quotation adjustment
---
# Quotation Pricing

## Default pricing factors

| Customer level | Default pricing factor |
|---|---|
| `vip` | `0.80` |
| `standard` | `0.90` |
| `new` | `1.00` |

These are reference defaults for the [customer levels](customer-knowledge.md).
The factor adjusts list prices and may be supplied per quotation; the creation
input explicitly requires `pricing_factor`. A default is not a guarantee that
every quotation for that customer level uses that value.
[^factor-defaults][^pricing-input][^pricing-docs]

## Calculation rules

```text
unit_price = list_price * pricing_factor
subtotal = unit_price * quantity
total_price = sum(subtotal)
profit_amount = sum((unit_price - product_cost) * quantity)
profit_rate = profit_amount / total_price
```

When `total_price` is zero, the service sets `profit_rate` to zero. Calculations
use the quotation items' list-price and product-cost snapshots.[^pricing-rules]

Modification restrictions are described in [Quotation Lifecycle](quotation-lifecycle.md).
An actual quotation's applied factor, prices, and profit must be read from the
Backend/API.

[^factor-defaults]: Default factor mapping recorded in frontmatter.
[^pricing-input]: Quotation creation input recorded in frontmatter.
[^pricing-rules]: Pricing implementation recorded in frontmatter.
[^pricing-docs]: Project pricing documentation recorded in frontmatter.
