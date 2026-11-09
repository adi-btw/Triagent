---
doc_id: RB-APP-001
type: runbook
title: Memory leak after a deploy
services: [all]
---
## Symptoms
After a new version ships, `container_memory_working_set_bytes` climbs in a
steady line instead of plateauing. Pods run normally for hours, then are
OOMKilled (exit code 137) and restart; the cycle repeats every few hours.
Latency worsens as pods approach the limit (more GC time), and brief error
bursts appear when several replicas restart close together.

## Diagnosis
1. Overlay memory per pod with deploy markers; a leak shows a slope that starts
   at the deploy and resets on each restart.
2. Compare the same panel for the previous version; a flat profile there
   confirms the regression is in the new release.
3. For Python services, capture a live stack and allocation view with
   `py-spy dump --pid 1`, or enable `tracemalloc` snapshots via the
   `/debug/memory` endpoint in staging.
4. Usual suspects: unbounded in-process caches, per-request objects appended to
   module-level lists, or client sessions created per request and never closed.

## Mitigation
- Roll back to the previous version (RB-DEPLOY-001); this is almost always
  faster than a forward fix.
- If rollback is blocked, temporarily raise the memory limit and add a
  scheduled `kubectl rollout restart` every few hours while the fix ships.
