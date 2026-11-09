---
doc_id: POL-ESC-001
type: policy
title: Paging and escalation
---
## Paging by severity
- SEV1: page the primary on-call immediately and the incident commander
  rotation; open #inc-<id> and update the public status page within 15 minutes.
- SEV2: page the primary on-call; acknowledge within 15 minutes. Status page
  update if customer impact lasts over 30 minutes.
- SEV3: create a ticket for the owning team; handle during business hours
  unless it worsens.
- SEV4: backlog ticket; no page.
Severity is set using POL-SEV-001 and may be raised at any time.

## Escalation
If the primary does not acknowledge within 10 minutes, the page escalates to the
secondary on-call, then to the engineering manager. A SEV1 not mitigated within
30 minutes escalates to the director on duty. Database changes on orders-db
during an incident (raising max_connections, failover, dropping slots) require
the DBA on-call.

## Third-party dependencies
For payment provider problems at SEV1 or SEV2, open a priority ticket with the
provider through its vendor portal and post the ticket number in the incident
channel. Provider status pages often lag the real impact; trust our own
dashboards first.
