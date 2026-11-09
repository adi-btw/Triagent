---
doc_id: RB-CACHE-001
type: runbook
title: Redis memory exhaustion and eviction
services: [redis-cache, cart-api, checkout-api]
---
## Symptoms
redis-cache stores cart sessions for cart-api and short-lived price lookups for
checkout-api. When memory runs out, clients see one of:
- `OOM command not allowed when used memory > 'maxmemory'` on writes (policy
  `noeviction`): cart updates fail, reads still work.
- A sudden rise in `evicted_keys` and cache misses (policy `allkeys-lru`):
  carts appear empty, latency rises from extra database reads.
- `Error 111 connecting to redis-cache:6379. Connection refused` if the Redis
  pod itself was OOMKilled by Kubernetes and is restarting.

## Diagnosis
1. `redis-cli -h redis-cache INFO memory` and compare `used_memory_human` with
   `maxmemory_human` (production: 6gb).
2. `redis-cli INFO stats | grep evicted_keys` to see eviction rate.
3. Find what grew: `redis-cli --bigkeys` and `redis-cli --memkeys`, and check
   for key prefixes written without a TTL (`OBJECT IDLETIME`, `TTL <key>`).
4. `kubectl -n prod describe pod redis-cache-0` and look for
   `Reason: OOMKilled`, which means the container limit is below maxmemory plus
   overhead.

## Mitigation
- Delete the offending prefix in batches: `redis-cli --scan --pattern 'reco:*' |
  xargs -n 500 redis-cli UNLINK`.
- Switch to `CONFIG SET maxmemory-policy volatile-lru` so only TTL'd keys evict.
- Keep the container memory limit at least 25% above maxmemory.
- Never run `FLUSHALL` in production: it logs out every cart session.
