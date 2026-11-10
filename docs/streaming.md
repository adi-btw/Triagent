# Streaming progress: `POST /triage/stream`

A triage takes about 1 s on a hosted model and up to a minute on a laptop CPU. A spinner
during that time says nothing. `/triage/stream` takes the same request body as `/triage`
and answers with Server-Sent Events while the pipeline runs. The person waiting sees the
evidence that was found, what the agent decided and why, and which model call is
running. The demo UI uses it by default.

Code: `app/triage/events.py` (the hook), `app/streaming.py` (SSE transport),
`app/static/app.js` (`readStream`, `onProgress`). Tests: `tests/test_streaming.py`, plus
the Docker smoke test in CI.

## Events

```
event: started       {"mode": "agent", "model": "gemini-3.5-flash-lite"}
event: step          {"step": {"name": "retrieve", "latency_ms": 41.2, "detail": {...}}}
event: evidence      {"items": [{"chunk_id", "title", "heading", "score", "method"}, ...]}
event: step_started  {"name": "decide"}
event: step          {"step": {"name": "decide", "detail": {"decision": "draft_report", ...}}}
event: step_started  {"name": "draft"}
event: step          {"step": {"name": "draft", ...}}
event: step          {"step": {"name": "validate", ...}}
event: result        {"http_status": 200, "response": <TriageResponse>}
```

Every stream ends with exactly one `result` or `error`:

* `result.response` is the body `/triage` would return, and `result.http_status` is the
  status `/triage` would use: 200, or 422 for a report the validator rejected. Tests check
  that both endpoints produce the same final body.
* `error` carries `http_status` 403 (key-free demo, not a sample), 429, 502 (provider
  failed), 503 (no index) or 500, with `detail` and `type`.

The HTTP status of the stream itself is 200. The status line is sent before the work
starts, so failures that happen during the run arrive as `error` events. Failures that
happen before it starts get their normal status code: request validation (422), the demo
rate limit (429), or an LLM that can't be built (503).

```bash
curl -N -X POST localhost:8000/triage/stream -H "Content-Type: application/json" \
  -d '{"incident": "checkout-api 500s: FATAL: sorry, too many clients already", "mode": "agent"}'
```

## Design decisions

**Stream progress, not report tokens.** Every claim in a report is checked against the
retrieved evidence before anyone sees it. Streaming the model's tokens as they arrive
would show citations and claims the validator may reject a second later, and on
`invalid_output` they would never be accepted at all. The report comes once, whole and
validated, in `result`. What streams is everything that's already true: the evidence
retrieved, the agent's decision and rationale, step timings.

**A hook, not a second pipeline.** The pipelines call `events.emit(...)` at a few points.
The listener sits in a `ContextVar`, so with no listener (`/triage`, the eval, the CLI)
`emit` does nothing, and each request in the thread pool sees only its own listener. There
is still one code path. A streamed triage and a plain one run identical code, which is why
their final bodies match.

**Thread to event loop.** Triage is blocking code, so it runs in a worker thread, as the
sync `/triage` handler does. Events cross to the event loop with
`loop.call_soon_threadsafe` into an `asyncio.Queue`. The worker runs in a copy of the
request's context, so the request id in logs carries over.

**SSE over `fetch`, not `EventSource`.** `EventSource` can only send GET requests with no
body, and an incident can be 8,000 characters. The UI POSTs with `fetch` and parses the
event stream from `response.body`, in about 30 lines. If the browser can't read a stream,
it falls back to `/triage`.

**Keep-alive and disconnects.** A `: ping` comment goes out every 15 s, so proxies don't
close a stream that's waiting on a slow local model. If the client leaves, the stream
stops writing. The worker finishes the current model call and ends. Interrupting a
blocking HTTP call mid-flight isn't safe, and the agent's step budget already bounds how
long the worker can run.

**Proxy buffering.** The response sets `Cache-Control: no-cache` and
`X-Accel-Buffering: no`, so nginx-style proxies pass events through as they're written
instead of holding them until the response ends.
