---
doc_id: RB-DB-003
type: runbook
title: PostgreSQL disk full from WAL growth
services: [orders-db]
---
## Symptoms
orders-db data volume usage climbs steadily (alert `PgDataVolumeUsage > 80%`)
while table sizes are flat. Most of the growth is in `pg_wal/`. If the disk
fills, Postgres logs `PANIC: could not write to file "pg_wal/xlogtemp.1234":
No space left on device` and the primary shuts down; every client then sees
"connection refused" on port 5432.

## Diagnosis
1. `du -sh /var/lib/postgresql/data/pg_wal` on the primary pod.
2. Find slots that pin WAL:
   `SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(),
   restart_lsn)) AS retained FROM pg_replication_slots;`
3. An inactive slot (`active = f`) retaining tens of GB is the usual cause,
   typically left behind by a decommissioned replica or reporting consumer.
4. Also check `archive_command` failures:
   `SELECT failed_count, last_failed_wal FROM pg_stat_archiver;`

## Mitigation
- Confirm with the slot owner that the consumer is gone, then
  `SELECT pg_drop_replication_slot('<slot_name>');`. WAL is recycled at the
  next checkpoint (`CHECKPOINT;` to force).
- If the disk is above 95%, expand the PVC first (`kubectl patch pvc
  data-orders-db-0 ...`); the storage class supports online expansion.
- Never delete files in `pg_wal/` by hand; it corrupts the cluster.
- Follow-up: set `max_slot_wal_keep_size = 50GB` so one slot cannot fill the disk.
