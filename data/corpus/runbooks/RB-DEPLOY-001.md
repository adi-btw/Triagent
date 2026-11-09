---
doc_id: RB-DEPLOY-001
type: runbook
title: Rolling back a bad deploy
services: [all]
---
## When to roll back
Roll back first and investigate second when error rate or latency rose within
about 30 minutes of a deploy and nothing else changed (no traffic spike, no
infrastructure change). Check the deploy log in #deploys or
`kubectl rollout history deployment/<service> -n prod`. If the deploy also
triggered a scale-out, check whether the scale-out is the real cause (for
example RB-DB-001) before assuming the code is at fault.

## Procedure
1. `kubectl rollout undo deployment/<service> -n prod` (or
   `--to-revision=<n>` for an older revision).
2. `kubectl rollout status deployment/<service> -n prod --timeout=5m`
3. Freeze further deploys of that service: add the `deploy-freeze` label in the
   pipeline UI.
4. Post the rollback in the incident channel with the old and new versions.

## Verification
Within 10 minutes the error rate should return to the pre-deploy baseline on the
service dashboard. If it does not, the deploy was probably not the cause; keep
the rollback in place and continue diagnosis.

## Caveats
- If the release ran a database migration, confirm the previous version is
  compatible with the new schema before rolling back. Destructive migrations
  (dropped columns) cannot be rolled back this way.
- Feature-flagged changes are faster to revert by turning the flag off.
