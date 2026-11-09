---
doc_id: RB-DB-004
type: runbook
title: PostgreSQL lock contention from long-running migrations
services: [orders-db, checkout-api, cart-api]
---
## Symptoms
Application pools report acquire timeouts (for example "pool.acquire timed out
after 5000ms") and requests pile up, but orders-db is NOT near
max_connections: active connections are typically well under half of the 200
limit. Postgres logs `canceling statement due to lock timeout` or
`process 4121 still waiting for AccessExclusiveLock on relation 16402`. Onset
usually lines up with a schema migration or a manual `ALTER TABLE`.

## Diagnosis
1. Find blocked sessions and their blockers:
   `SELECT pid, pg_blocking_pids(pid) AS blocked_by, wait_event_type,
   left(query, 80) FROM pg_stat_activity WHERE wait_event_type = 'Lock';`
2. Inspect the blocker: `SELECT pid, now() - xact_start AS age, query FROM
   pg_stat_activity WHERE pid = <blocker>;`
3. Typical blockers: `ALTER TABLE ... ADD COLUMN ... DEFAULT` on old Postgres,
   `CREATE INDEX` without `CONCURRENTLY`, or an idle-in-transaction session
   holding a lock.
4. If connections ARE near max_connections and there are no Lock waits, this is
   connection exhaustion instead; use RB-DB-001.

## Mitigation
- Cancel the blocker: `SELECT pg_cancel_backend(<pid>);`, then
  `pg_terminate_backend(<pid>)` if it does not exit within 30s.
- Pause the migration job in the deploy pipeline so it does not retry.
- Waiting requests drain on their own once the lock is released.

## Prevention
Run migrations with `SET lock_timeout = '3s'` and retry, build indexes with
`CREATE INDEX CONCURRENTLY`, and schedule large table rewrites outside peak.
