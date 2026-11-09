---
doc_id: POL-SEV-001
type: policy
title: Incident severity levels
---
## Levels
- SEV1: Checkout or payments fully unavailable, or >50% error rate on a revenue
  path, or any data loss/security exposure.
- SEV2: Revenue path degraded (5–50% errors or p95 latency >3x baseline), or a
  core internal system down with no workaround.
- SEV3: Non-revenue feature degraded, or revenue path <5% errors.
- SEV4: No customer impact; internal tooling or cosmetic issues.

## Revenue paths
checkout-api, payments-api, and cart-api are revenue paths. search-api,
recommendations-api, and notifications-api are not.
