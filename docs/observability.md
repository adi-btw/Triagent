# Observability

Every response carries a `Trace` (steps, timings, token counts, violations, LLM calls).
`app/observability.py` turns that one record into logs, metrics and spans, so the three
always agree with what the API returned. The pipeline code contains no telemetry calls.

## Request ids

`X-Request-ID` is accepted from the caller when it's well-formed (`[A-Za-z0-9._-]{1,64}`), and
minted otherwise. It's echoed on the response and stamped on every log line and span. A
user's "request 3f2a… gave SEV1" maps straight to the logs.

## Structured logs

`LOG_FORMAT=json` writes one JSON object per line, ready for Loki, CloudWatch or Datadog. The
default `text` format is for local runs:

```
2026-11-09 22:49:19,632 INFO [demo-1] triage_completed mode=rag status=ok severity=SEV2 latency_ms=11.5 llm_calls=1 tokens_in=171 tokens_out=171 retrieved=5
2026-11-09 22:49:19,633 INFO [demo-1] http_request method=POST route=/triage status_code=200 duration_ms=14.9
```

Each triage emits `triage_completed`, with mode, status, severity, latency, LLM calls,
cache hits, tokens, violation types and the model. Each request also emits an `http_request`
access line. **Incident text is never logged**, because it can contain customer data. A test
enforces this.

## Metrics: `GET /metrics` (Prometheus)

| Metric | Labels | Use |
|---|---|---|
| `triagent_triage_requests_total` | mode, status | Throughput; the `invalid_output` share is the validator rejection rate |
| `triagent_triage_duration_seconds` | mode | p50/p95 latency per pipeline |
| `triagent_step_duration_seconds` | step | Which step is slow: retrieve, decide, draft, repair or validate |
| `triagent_llm_calls_total` | mode | Agent cost relative to RAG |
| `triagent_llm_tokens_total` | direction | Token spend |
| `triagent_llm_cost_usd_total` | | Only when `LLM_PRICE_INPUT_PER_MTOK` / `LLM_PRICE_OUTPUT_PER_MTOK` are set |
| `triagent_llm_cache_hits_total` | | Demo and eval cache effectiveness |
| `triagent_validation_violations_total` | type | Citation errors vs output-guard hits (possible injection attempts) |
| `triagent_reports_by_severity_total` | severity | Drift in what the tool is concluding |
| `triagent_http_errors_total` | route, status | 403 / 422 / 429 / 502 / 503 rates |

Alerts worth having: a rising `unsafe_action` or `untrusted_link` violation rate (an injection
campaign, or a poisoned document in the corpus), the `invalid_output` share above its baseline
(a model or prompt regression), and p95 latency.

## Traces: OpenTelemetry (optional)

`pip install -e ".[otel]"` and `OTEL_ENABLED=true`. Each request exports a `triage` span with a
child span per pipeline step. The spans are reconstructed from the measured step latencies, and
attributes include mode, status, severity, tokens, violations and `gen_ai.request.model`. The
exporter is configured with the standard `OTEL_EXPORTER_OTLP_*` variables, so Jaeger, Tempo,
Honeycomb or any other OTLP backend works.
