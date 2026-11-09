---
doc_id: RB-NET-002
type: runbook
title: Upstream timeouts caused by DNS resolution failures
services: [all]
---
## Symptoms
Requests time out after 5000ms. Logs show "getaddrinfo EAI_AGAIN" or
"Temporary failure in name resolution". Often follows a CoreDNS restart.

## Diagnosis
Run `kubectl -n kube-system logs deploy/coredns`. Check for SERVFAIL spikes.

## Mitigation
Restart CoreDNS pods; confirm ndots setting in pod dnsConfig.
