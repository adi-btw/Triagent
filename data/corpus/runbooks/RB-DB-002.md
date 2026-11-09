---
doc_id: RB-DB-002
type: runbook
title: PostgreSQL replica replication lag
services: [orders-db, inventory-api, checkout-api]
---
## Symptoms
Reads served from the orders-db read replica (`orders-db-replica-0`) return stale
data: stock counts that do not match the primary, or order status stuck on
"pending" for minutes after payment. Writes are unaffected and error rates are
usually flat. The `pg_replication_lag_seconds` panel rises above the 30s alert
threshold; values of several hundred seconds are common during bulk jobs.

## Diagnosis
1. On the primary: `SELECT client_addr, state, sent_lsn, replay_lsn,
   replay_lag FROM pg_stat_replication;`
2. On the replica: `SELECT now() - pg_last_xact_replay_timestamp() AS lag;`
3. If `sent_lsn` is far ahead of `replay_lsn`, the replica cannot apply WAL fast
   enough. Check replica disk IOPS and CPU (`iostat -x 5`); a saturated volume
   is the usual cause.
4. Look for a bulk write on the primary (backfill, `UPDATE` without batching,
   `VACUUM FULL`) that started shortly before lag began.
5. If `state` is not `streaming`, the replica has disconnected; see the replica
   logs for "could not receive data from WAL stream".

## Mitigation
- Pause or throttle the bulk job generating WAL (batch to 5,000 rows with a
  sleep between batches).
- Route lag-sensitive reads to the primary: set `READ_FROM_REPLICA=false` on
  inventory-api while lag exceeds 30s. Check primary connection headroom first
  (see RB-DB-001) before moving read traffic.
- Do not restart the replica to "clear" lag; it resumes from the same LSN.
