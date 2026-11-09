---
doc_id: RB-DB-001
type: runbook
title: PostgreSQL connection exhaustion
services: [orders-db, checkout-api, inventory-api]
---
## Symptoms
Clients fail with "FATAL: sorry, too many clients already" (SQLSTATE 53300) or
"remaining connection slots are reserved". Application-side pools report acquire
timeouts. Error rate usually rises within minutes of a scale-out or deploy.

## Diagnosis
1. Run `SELECT count(*), usename, application_name FROM pg_stat_activity GROUP BY 2,3;`
2. Compare total against `SHOW max_connections;` (orders-db: 200).
3. Compute expected demand: replicas × per-pod pool size. If demand exceeds
   max_connections minus 10 reserved slots, the pool configuration is the cause.

## Mitigation
- Fastest: scale the deployment back to its previous replica count.
- Or lower `DB_POOL_SIZE` so replicas × pool size stays under 190.
- Do NOT raise max_connections on orders-db without DBA approval; each
  connection costs ~10 MB of memory.
- Long term: route through PgBouncer in transaction mode.
