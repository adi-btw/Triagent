---
doc_id: RB-CDN-001
type: runbook
title: CDN cache purge storm overloading origin
services: [cdn, object-store]
---
## Symptoms
CDN cache hit ratio drops sharply (normally ~95% for static assets) right after
a purge, and origin request rate jumps 10-20x. The object store (`assets`
bucket) returns `503 SlowDown: Please reduce your request rate`, and the CDN
serves 503 or 504 for product images, JS bundles and CSS. Pages load without
images or styles; API services may be healthy.

## Diagnosis
1. CDN dashboard: hit ratio and origin requests per second for the last hour.
2. Purge audit log: `cdnctl purge history --since 2h`. Look for a purge-all,
   a wildcard such as `/*`, or a CI job issuing thousands of single-URL purges.
3. Object store metrics: 503 count and request rate on the `assets` bucket.

## Mitigation
- Stop the source of purges (disable the CI job or revoke its CDN token).
- Enable serve-stale: `cdnctl config set stale-if-error=86400
  stale-while-revalidate=600` so the CDN serves old copies while origin
  recovers.
- Turn on origin shield so only one CDN tier fetches from the object store.
- The hit ratio recovers by itself as the cache refills; do not purge again.
