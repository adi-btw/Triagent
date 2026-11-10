# Integrations: alert webhooks and Slack

Triagent can sit in the alert path. An alert fires, Triagent triages it against the
runbooks, and the report lands in a Slack channel. On-call can also type
`/triage <what is happening>` in Slack.

```
Alertmanager / Grafana / curl ──POST /webhooks/alert──▶ triage ──▶ Slack incoming webhook
Slack  /triage ...            ──POST /slack/commands──▶ triage ──▶ reply in the same channel
```

Code: `app/integrations/` (`alerts.py` parsing and dedupe, `slack.py` formatting and
signatures, `routes.py` endpoints). Tests: `tests/test_integrations.py`.

Every endpoint is **off until its secret is set**. A deployment that never configured
them, like the public demo, returns 503 and exposes nothing new.

| Setting | Enables |
|---|---|
| `WEBHOOK_TOKEN` | `POST /webhooks/alert` (callers send `Authorization: Bearer <token>`) |
| `SLACK_WEBHOOK_URL` | posting alert triage to a channel (otherwise the result is logged) |
| `SLACK_SIGNING_SECRET` | `POST /slack/commands` |
| `INTEGRATION_MODE` | `rag` (default) or `agent` |
| `ALERT_DEDUPE_TTL_S` | how long a re-sent alert group is ignored (default 1 h) |
| `INTEGRATION_TRIAGES_PER_HOUR` | cap on triages from both endpoints (default 60) |

`GET /health` reports which integrations are on as booleans, never the secrets or the
webhook URL. The webhook URL is itself a credential.

## Try it locally, free

No Slack and no API key needed: the fake LLM answers, and the Slack message is logged.

```bash
LLM_PROVIDER=fake WEBHOOK_TOKEN=local-test uvicorn app.main:app --port 8000
curl -X POST "localhost:8000/webhooks/alert?wait=true" \
  -H "Authorization: Bearer local-test" -H "Content-Type: application/json" \
  --data @examples/alertmanager-firing.json
```

`?wait=true` triages inline and returns the full `TriageResponse`. Without it the
endpoint answers `202` at once and triages in the background, which is what Alertmanager
needs. For real answers at no cost, use a local model:
`LLM_PROVIDER=openai_compat OPENAI_MODEL=qwen2.5:3b` (see the README's model comparison).

To see real Slack messages, create a free workspace, add an app with an *Incoming
Webhook*, and set `SLACK_WEBHOOK_URL`. For the slash command, add a `/triage` command
pointing at `https://<your host>/slack/commands`, and copy the app's *Signing Secret*
into `SLACK_SIGNING_SECRET`. Slack has to reach your server, so for local testing that
means a tunnel such as `cloudflared tunnel --url localhost:8000`.

## Alert sources

**Alertmanager** (and Grafana's Alertmanager-compatible contact point):

```yaml
receivers:
  - name: triagent
    webhook_configs:
      - url: https://triagent.example.internal/webhooks/alert
        http_config:
          authorization: { type: Bearer, credentials_file: /etc/alertmanager/triagent-token }
        send_resolved: false
```

Each alert group becomes **one** incident: alerts are grouped because they share a cause.
The incident text has the common summary, then each alert's annotations, labels and start
time, up to 10 alerts. Resolved alerts are dropped.

**Anything else** can POST `{"title": ..., "description": ..., "service"?, "severity"?}`.

## Design decisions

**Answer first, triage after.** One triage takes 1–40 s depending on the model.
Alertmanager times out and retries slow receivers, and Slack shows an error if a slash
command isn't answered within 3 s. So both endpoints check auth, parse, dedupe, reply,
and hand off to a FastAPI background task. Results and failures arrive in Slack. If the
LLM provider fails, the channel gets "Triage failed" with the error type, rather than
silence. In-process background tasks are lost if the process restarts mid-triage. A queue
(Redis, SQS) would fix that, and isn't worth it at this scale.

**Deduplicate re-sends.** Alertmanager re-sends a still-firing group every
`repeat_interval`. Without dedupe, each resend is another LLM call and another Slack
message. The key is the group key plus each alert's fingerprint and start time, so a new
firing of the same alert (a new `startsAt`) is triaged again. The dedupe memory is
per-process; with several replicas it would live in Redis.

**Cap the cost of an alert storm.** A sliding-window limit (`INTEGRATION_TRIAGES_PER_HOUR`)
covers both endpoints. Past the limit, the webhook answers 429 with `Retry-After`, and
the slash command replies that the limit is reached.

**Model output can't ping or phish.** Slack mrkdwn treats `<...>` as control syntax:
`<!channel>` notifies everyone and `<https://x|text>` hides a link. Reports are model
output derived from alert text that an attacker may control, so every model-written string
is escaped (`& < >`) before it's placed in a block. Mentions and links can only come from
Triagent's own template. Tests check that `<!channel>` and hidden links come through as
inert text.

**A rejected report is posted as rejected.** If the validator returns `invalid_output`,
the Slack message says so and lists the violations, but not the report itself. Posting it
would put an unchecked answer in the channel looking like a checked one. The same goes for
abstention ("Not enough evidence in the runbooks") and agent clarifying questions.

**Verified Slack requests only.** Slash commands are checked with Slack's v0 signature:
HMAC-SHA256 over `v0:{timestamp}:{raw body}`, constant-time compare, and timestamps
older than 5 minutes refused, which blocks replays. The raw body is read before parsing,
because Slack signs the bytes, not the fields.

**No SSRF through `response_url`.** A slash command carries the URL to reply to. Triagent
only POSTs to `https://hooks.slack.com/...`. Even with a leaked signing secret, the server
can't be aimed at an internal address such as the cloud metadata endpoint.

## Metrics

`triagent_integration_events_total{source, outcome}` with `source` of `alertmanager`,
`generic` or `slack`, and outcomes `accepted`, `duplicate`, `ignored`, `rate_limited`,
`unauthorized`, `delivered`, `delivery_failed`, `not_configured` and `bad_response_url`.
Each triage is also counted in the usual `triagent_triage_*` metrics.
