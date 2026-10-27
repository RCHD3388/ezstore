---
type: Reference
title: Customer Knowledge
description: Customer attributes, levels, and relationships.
tags: [ezstore, customers, sales-insight]
sources:
  - id: customer-model
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/models/customer.go#L10-L22
    title: Customer fields
  - id: customer-validation
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/services/customer_service.go#L71-L85
    title: Allowed customer levels and credit-score range
  - id: quotation-customer
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/models/quotation.go#L16-L18
    title: Quotation customer reference
  - id: order-customer
    resource: https://github.com/RCHD3388/ezstore/blob/32f11e2226bc8584115f7c50c0b1b461932456eb/backend/models/order.go#L16-L19
    title: Order customer reference
---
# Customer Knowledge

## Attributes and levels

| Field | Meaning |
|---|---|
| `id` | Customer identifier |
| `name`, `tax_id` | Customer/company name and tax identifier |
| `contact_name`, `contact_phone`, `contact_email` | Contact information |
| `address` | Customer address |
| `level` | Customer level: `vip`, `standard`, or `new` |
| `credit_score` | Integer credit score in the range 0-100 |

The model defines these attributes; validation restricts the level and credit
score as shown.[^customer-model][^customer-validation]

## Relationships

Quotations and orders each reference a customer through `customer_id`.
Their actual records and customer sales activity are live Backend data.
[^quotation-customer][^order-customer]

See [Quotation Pricing](quotation-pricing.md) for customer-level defaults and
[Quotation-Order Relationship](quotation-order-relationship.md) for order linkage.

[^customer-model]: Customer field definitions recorded in frontmatter.
[^customer-validation]: Customer validation recorded in frontmatter.
[^quotation-customer]: Quotation customer reference recorded in frontmatter.
[^order-customer]: Order customer reference recorded in frontmatter.
