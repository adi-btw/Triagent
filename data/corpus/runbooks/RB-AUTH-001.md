---
doc_id: RB-AUTH-001
type: runbook
title: JWT signing key rotation failure
services: [auth-service, checkout-api, cart-api]
---
## Symptoms
After auth-service rotates its JWT signing key, services that verify tokens
reject them with HTTP 401 and log `invalid token: kid "k-2026-10" not found in
JWKS` or `signature verification failed`. Users are logged out or see
"Session expired" on every action. Failures hit all token-verifying services
at once and begin at the rotation time, not at a deploy.

## Diagnosis
1. Fetch the published key set: `curl -s
   https://auth-service.internal/.well-known/jwks.json | jq '.keys[].kid'`.
2. Decode a failing token header (`echo <token> | cut -d. -f1 | base64 -d`) and
   compare its `kid` with the JWKS list.
3. Verifiers cache JWKS for 1 hour (`JWKS_CACHE_TTL=3600`). If the new kid was
   used for signing before verifiers refreshed, tokens fail until caches expire.
4. Rotation history: `authctl keys list` shows `active`, `published`, and
   `retired` keys with timestamps.

## Mitigation
- Revert signing to the previous key: `authctl keys activate <previous-kid>`.
  Keep both keys published in JWKS.
- Force verifiers to refresh: `kubectl rollout restart deployment/checkout-api
  deployment/cart-api -n prod`.
- Correct rotation order: publish the new key, wait at least one JWKS cache TTL,
  then activate it for signing, and retire the old key only after token max
  lifetime (24h).
