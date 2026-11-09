---
doc_id: RB-NET-003
type: runbook
title: Unexpected 429s from ingress rate limiting
services: [checkout-api, cart-api, search-api]
---
## Symptoms
Clients receive `429 Too Many Requests` from the ingress, not from the
application. ingress-nginx logs show `limiting requests, excess: 20.500 by zone
"checkout-api-rps", client: 203.0.113.10`. Application pods see lower traffic
than normal and their own error logs are quiet. Often follows a change to
`nginx.ingress.kubernetes.io/limit-rps` or to the CDN or proxy in front of the
ingress.

## Diagnosis
1. Check whether the limited `client` addresses are CDN or NAT egress IPs. If
   thousands of users share a few IPs, a per-IP limit throttles everyone.
2. `kubectl get ingress <service> -n prod -o yaml | grep limit` to read the
   current limit annotations.
3. Confirm the ingress trusts the forwarded client IP: `use-forwarded-headers`
   and `proxy-real-ip-cidr` in the ingress-nginx ConfigMap.
4. Rule out real abuse: a small number of distinct real client IPs with very
   high rates is an attack, not a misconfiguration.

## Mitigation
- Revert the annotation change, or raise `limit-rps` while the key is fixed.
- Set `use-forwarded-headers: "true"` and the CDN ranges in
  `proxy-real-ip-cidr` so limits apply per real client.
