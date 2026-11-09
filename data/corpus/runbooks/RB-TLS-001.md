---
doc_id: RB-TLS-001
type: runbook
title: TLS certificate expiry
services: [all]
---
## Symptoms
Callers fail immediately (no timeout) with errors such as
`x509: certificate has expired or is not yet valid`,
`SSL: CERTIFICATE_VERIFY_FAILED certificate verify failed: certificate has
expired`, or browsers show `NET::ERR_CERT_DATE_INVALID`. Failure is total for
every client of the affected endpoint, starting at the exact `notAfter` time.
Internal mTLS links (payments-api to the card vault, services to auth-service)
are affected the same way.

## Diagnosis
1. Check the served certificate:
   `openssl s_client -connect payments-api.internal:443 -servername
   payments-api.internal </dev/null | openssl x509 -noout -dates -subject`
2. `kubectl get certificate -A` and look for `READY=False`.
3. `kubectl describe certificate <name> -n <ns>` and the matching
   `CertificateRequest`/`Order` for ACME or issuer errors (for example
   "failed to perform self check" or "issuer credentials invalid").

## Mitigation
- Force renewal: `cmctl renew <name> -n <ns>`, then confirm `READY=True` and
  restart pods that do not hot-reload certificates.
- If the issuer is broken, fix the `ClusterIssuer` secret first; renewal will
  not succeed until it reports `Ready`.
- Prevention: alert when any certificate expires in under 14 days
  (`certmanager_certificate_expiration_timestamp_seconds - time() < 1209600`).
