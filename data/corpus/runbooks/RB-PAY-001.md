---
doc_id: RB-PAY-001
type: runbook
title: Payment provider errors and timeouts
services: [payments-api, checkout-api]
---
## Symptoms
payments-api calls the primary card processor, PayFlux, with a 5000ms client
timeout. During a provider problem, logs show
`PayFluxError: upstream returned 502 Bad Gateway`, `503 Service Unavailable`
from `api.payflux.example`, or `httpx.ReadTimeout: provider call exceeded
5000ms`. DNS resolves normally and the database is healthy; only the outbound
provider call fails. checkout-api surfaces these as "Payment could not be
processed".

## Diagnosis
1. Dashboard "payments-api / provider" panel: error rate and latency split by
   provider. Failures limited to PayFlux point at the provider.
2. Check the PayFlux status page and the vendor channel #vendor-payflux.
3. Circuit breaker state: `curl -s payments-api:8080/admin/breakers | jq` and
   look for `payflux: open` or `half_open`.
4. If timeouts also hit other hosts, suspect DNS (RB-NET-002) or egress
   instead of the provider.

## Mitigation
- Fail over to the secondary processor, Ledgerly:
  `paymentsctl provider set-primary ledgerly --reason INC-<id>`. Ledgerly
  supports Visa and Mastercard only; Amex payments will still fail.
- Never blind-retry charges. Retries must reuse the same `Idempotency-Key`
  or customers can be double charged.
- Open a priority ticket with PayFlux for SEV1 or SEV2 (see POL-ESC-001).
