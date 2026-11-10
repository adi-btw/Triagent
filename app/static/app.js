// Triagent UI for POST /triage. Vanilla JS, no build step, no external dependencies.
//
// Safety note: everything shown comes from the model or the corpus, so it is written with
// textContent / createElement, never innerHTML. A report that contains "<script>" is
// displayed as text, not executed.
"use strict";

const DEMO_INCIDENT = `checkout-api returning 500s since ~14:05 UTC, roughly 18% of requests.
We deployed v2.31.0 at 13:58 and the HPA scaled checkout-api from 6 to 14 pods.

2026-11-09T14:06:12Z ERROR checkout-api  pool.acquire timed out after 5000ms
2026-11-09T14:06:12Z ERROR checkout-api  psycopg.OperationalError: connection failed:
                     FATAL: sorry, too many clients already
2026-11-09T14:06:13Z WARN  orders-db     connections active=197 max_connections=200`;

const VAGUE_INCIDENT = "Payments seem flaky? Customers are complaining.";

const MODE_LABELS = { no_retrieval: "Baseline", rag: "RAG", agent: "Agent" };

const $ = (id) => document.getElementById(id);

// The last request sent, so a clarification can resubmit the same incident and mode.
let lastRequest = null;
let loadingTimer = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined && child !== false) {
      node.append(child instanceof Node ? child : String(child));
    }
  }
  return node;
}

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function formatMs(ms) {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`;
}

// ------------------------------------------------------------------ busy / loading state

function setBusy(busy) {
  for (const button of document.querySelectorAll("button:not(#theme-toggle)")) button.disabled = busy;
  $("submit-label").textContent = busy ? "Triaging…" : "Run triage";

  clearInterval(loadingTimer);
  $("loading").hidden = !busy;
  if (busy) {
    $("empty").hidden = true;
    $("result").hidden = true;
    const mode = lastRequest ? lastRequest.mode : selectedMode();
    $("loading-text").textContent = {
      no_retrieval: "Drafting a report without retrieval…",
      rag: "Retrieving evidence and drafting the report…",
      agent: "Agent is searching, deciding and drafting…",
    }[mode];
    const started = performance.now();
    $("loading-timer").textContent = "0.0s";
    loadingTimer = setInterval(() => {
      $("loading-timer").textContent = `${((performance.now() - started) / 1000).toFixed(1)}s`;
    }, 100);
  }
}

function showError(title, detail) {
  const box = $("error");
  box.replaceChildren(el("strong", { text: title }));
  if (detail) box.append(el("span", { text: detail }));
  box.hidden = false;
}

function errorDetail(body) {
  if (!body) return "";
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    // FastAPI request validation: [{loc: [...], msg: "..."}]
    return body.detail.map((d) => `${(d.loc || []).join(".")}: ${d.msg}`).join("; ");
  }
  return JSON.stringify(body);
}

async function submitTriage(payload) {
  lastRequest = payload;
  $("error").hidden = true;
  $("clarify").hidden = true;
  setBusy(true);
  try {
    const resp = await fetch("/triage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    let body = null;
    try { body = await resp.json(); } catch { /* non-JSON error page */ }

    // 200 ok / needs_clarification, and 422 *with* "status" (report failed validation),
    // are both full TriageResponse bodies. A 422 without "status" is a bad request.
    if (body && typeof body.status === "string" && (resp.ok || resp.status === 422)) {
      setBusy(false);
      renderResponse(body);
      return;
    }
    setBusy(false);
    $("empty").hidden = false;
    const titles = {
      422: "The request was rejected",
      403: "Only the sample incidents work in this demo",
      429: "Demo limit reached",
      501: "This mode is not available on the server",
      502: "The language model provider failed",
      503: "The server is not fully configured",
    };
    showError(titles[resp.status] || `Request failed (HTTP ${resp.status})`, errorDetail(body));
  } catch (err) {
    setBusy(false);
    $("empty").hidden = false;
    showError("Could not reach the server", String(err));
  }
}

// ------------------------------------------------------------------ rendering

function renderResponse(body) {
  const evidenceIds = new Set((body.evidence || []).map((e) => e.chunk_id));
  const report = body.report;

  $("empty").hidden = true;
  renderClarification(body);
  renderHead(body, report, evidenceIds);
  renderStats(body);
  renderReport(report, evidenceIds);
  renderViolations(body.trace.violations);
  renderTimeline(body.trace.steps);
  renderEvidence(body.evidence || []);

  $("result").hidden = false;
  if (body.status !== "needs_clarification") {
    $("result").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function renderHead(body, report, evidenceIds) {
  $("report-head").hidden = !report;
  const badge = $("status-badge");
  badge.className = `badge ${body.status}`;
  badge.textContent = body.status.replaceAll("_", " ");
  $("mode-badge").textContent = `${MODE_LABELS[body.trace.mode] || body.trace.mode} · ${body.trace.model}`;
  if (!report) return;

  const sev = report.severity;
  $("sev-tile").className = `sev-tile ${sev ? `sev-${sev}` : "sev-unknown"}`;
  $("severity").textContent = sev || "Unknown";
  $("severity-cites").replaceChildren(
    report.severity_citations.length ? chips(report.severity_citations, evidenceIds) : "");
  $("summary").textContent = report.summary;
  $("abstain").hidden = !report.insufficient_evidence;
}

function renderStats(body) {
  const t = body.trace.timings_ms || {};
  const pinned = (body.evidence || []).filter((e) => e.method === "pinned").length;
  const searched = (body.evidence || []).length - pinned;
  const items = [
    ["Total time", formatMs(t.total)],
    ["LLM calls", String(body.trace.llm_calls)],
    ["Evidence", pinned ? `${searched} + ${pinned} pinned` : String(searched)],
    ["Retrieval", body.trace.retrieval_mode || "none", true],
  ];
  $("stats").replaceChildren(...items.map(([label, value, small]) =>
    el("div", {}, el("dt", { text: label }), el("dd", { class: small ? "small-val" : "", text: value }))));
}

function renderClarification(body) {
  const needed = body.status === "needs_clarification";
  $("clarify").hidden = !needed;
  if (needed) {
    $("clarify-question").textContent = body.clarifying_question;
    $("clarification").value = "";
    $("clarify").scrollIntoView({ behavior: "smooth", block: "center" });
    $("clarification").focus({ preventScroll: true });
  }
}

function renderReport(report, evidenceIds) {
  $("report-body").hidden = !report;
  $("missing-wrap").hidden = !report || !report.missing_information.length;
  if (!report) return;

  const causes = report.likely_causes.map((c) =>
    el("li", {},
      el("div", { class: "cause-top" },
        el("span", { class: `conf conf-${c.confidence}`, text: c.confidence }),
        el("span", { text: c.description })),
      chips(c.citations, evidenceIds)));
  $("causes").replaceChildren(...(causes.length ? causes : [emptyItem("No causes stated.")]));

  const steps = report.next_steps.map((s) =>
    el("li", {}, el("span", { text: s.action }), chips(s.citations, evidenceIds)));
  $("steps").replaceChildren(...(steps.length ? steps : [emptyItem("No next steps stated.")]));

  $("missing").replaceChildren(...report.missing_information.map((m) => el("li", { text: m })));
}

function emptyItem(text) {
  return el("li", { class: "empty", text });
}

function chips(ids, evidenceIds) {
  const wrap = el("span", { class: "chips" });
  if (!ids.length) {
    wrap.append(el("span", { class: "chip unknown", text: "no citation" }));
    return wrap;
  }
  for (const id of ids) {
    const known = evidenceIds.has(id);
    const chip = el("button", {
      type: "button",
      class: known ? "chip" : "chip unknown",
      text: id,
      "aria-label": known ? `Show evidence ${id}` : `${id}: not in the retrieved evidence`,
      title: known ? "Show this passage" : "Not in the retrieved evidence",
    });
    chip.addEventListener("click", () => openEvidence(id, known));
    wrap.append(chip);
  }
  return wrap;
}

function openEvidence(id, known) {
  if (!known) {
    showError("Unknown citation", `${id} was not retrieved for this request, so it cannot be shown.`);
    return;
  }
  const details = document.querySelector(`#evidence details[data-id="${CSS.escape(id)}"]`);
  if (!details) return;
  details.open = true;
  details.classList.add("flash");
  setTimeout(() => details.classList.remove("flash"), 1400);
  details.scrollIntoView({ behavior: "smooth", block: "center" });
  details.querySelector("summary").focus({ preventScroll: true });
}

function renderViolations(violations) {
  $("violations-wrap").hidden = !violations.length;
  $("violations").replaceChildren(...violations.map((v) =>
    el("li", {}, el("code", { text: v.type }), ": ", v.detail)));
}

function renderEvidence(evidence) {
  // Bars are relative to the best search score in this response (scores differ by mode:
  // cosine for vector, BM25 for keyword, RRF for hybrid), so only the ranking is shown.
  const searchScores = evidence.filter((e) => e.method !== "pinned").map((e) => e.score);
  const maxScore = Math.max(...searchScores, 0) || 1;

  const items = evidence.map((e) => {
    const pinned = e.method === "pinned";
    const right = pinned
      ? el("span", { class: "tag", text: "Pinned", title: "Always included, not a search result" })
      : el("span", { class: "ev-score" },
          el("span", { class: "ev-score-text", text: `${e.method} ${e.score.toFixed(3)}` }),
          el("span", { class: "bar", "aria-hidden": "true" },
            el("span", { style: `width:${Math.max(4, (e.score / maxScore) * 100).toFixed(0)}%` })));
    return el("details", { "data-id": e.chunk_id },
      el("summary", {},
        el("span", { class: "ev-left" },
          el("span", { class: "ev-id", text: e.chunk_id }),
          el("span", { class: "ev-title", text: `${e.title} · ${e.heading}` })),
        right),
      el("pre", { text: e.content }));
  });
  $("evidence").replaceChildren(
    ...(items.length ? items : [el("p", { class: "muted small", text: "No evidence for this request." })]));
}

// ------------------------------------------------------------------ steps timeline

function truncate(text, n = 120) {
  const flat = String(text ?? "").replace(/\s+/g, " ").trim();
  return flat.length > n ? `${flat.slice(0, n - 1)}…` : flat;
}

// One line of explanation per step type; the raw detail is still in the JSON response.
function describeStep(step) {
  const d = step.detail || {};
  switch (step.name) {
    case "retrieve": {
      const added = d.new_chunk_ids ? `, ${d.new_chunk_ids.length} new` : "";
      const pinned = d.pinned && d.pinned.length ? ` + ${d.pinned.length} pinned` : "";
      return `“${truncate(d.query, 70)}” → ${(d.results || []).length} chunks${added}${pinned}`;
    }
    case "decide":
      return d.decision ? `${d.decision.replaceAll("_", " ")}: ${d.rationale}` : `malformed output (${truncate(d.error)})`;
    case "override":
      return `${d.requested_action || "no decision"} → ${d.action}: ${d.reason}`;
    case "rewrite_query":
      return `new query: “${truncate(d.query, 100)}”`;
    case "ask_clarifying_question":
      return d.question;
    case "generate":
    case "draft":
    case "repair": {
      const fed = d.violations_fed_back ? `${d.violations_fed_back.length} violation(s) fed back; ` : "";
      return `${fed}${d.parsed_json === false ? "output was not JSON" : "structured JSON report"}` +
        (d.output_tokens != null ? ` · ~${d.output_tokens} output tokens` : "");
    }
    case "validate": {
      const n = (d.violations || []).length;
      const verdict = n ? `${n} violation(s)` : "all citations valid";
      const repair = d.repair ? `; repair ${d.repair}` : "";
      return `${verdict} · ${(d.allowed_ids || []).length} allowed ids${repair}`;
    }
    default:
      return truncate(JSON.stringify(d));
  }
}

const STEP_GLYPH = {
  retrieve: "R", decide: "D", rewrite_query: "Q", ask_clarifying_question: "?",
  generate: "G", draft: "G", repair: "F", validate: "✓", override: "!",
};

function renderTimeline(steps) {
  const total = steps.reduce((sum, s) => sum + s.latency_ms, 0);
  $("trace-summary").textContent = `${steps.length} steps · ${formatMs(total)}`;
  $("timeline").replaceChildren(...steps.map((step) => {
    const failed = step.name === "validate" && (step.detail.violations || []).length;
    const kind = failed ? "fail" : step.name;
    return el("li", {},
      el("span", { class: `step-dot kind-${kind}`, "aria-hidden": "true", text: failed ? "✕" : STEP_GLYPH[step.name] || "·" }),
      el("span", { class: "step-body" },
        el("span", { class: "step-name", text: step.name.replaceAll("_", " ") }),
        el("span", { class: "step-detail", text: describeStep(step) })),
      el("span", { class: "step-latency", text: formatMs(step.latency_ms) }));
  }));
}

// ------------------------------------------------------------------ header: health + theme

async function loadHealth() {
  const pill = $("health");
  try {
    const resp = await fetch("/health");
    const h = await resp.json();
    const problems = [];
    if (!h.index_ok) problems.push("index missing");
    if (h.llm_provider === "gemini" && !h.llm_key_present && !h.demo_samples_only) {
      problems.push("no API key");
    }
    pill.dataset.state = problems.length ? "warn" : "ok";
    $("health-text").textContent = problems.length
      ? problems.join(" · ")
      : h.demo_samples_only
        ? `demo · ${h.retrieval_mode} · recorded ${h.model} runs`
        : `${h.model} · ${h.retrieval_mode}`;
    pill.title = `backend: ${h.backend}, embedder: ${h.embedder}, provider: ${h.llm_provider}` +
      (h.index_error ? `\n${h.index_error}` : "");
    if (h.demo_mode) {
      const note = $("demo-note");
      note.textContent = h.demo_samples_only
        ? "Public demo. Pick a sample incident and any pipeline: the answers are real runs of " +
          `${h.model}, recorded ahead of time. Custom incidents need the model, so run Triagent ` +
          "locally for those (see the README)."
        : "Public demo. The sample incidents are pre-computed and load instantly; custom " +
          `incidents call the model live, up to ${h.demo_requests_per_hour} per hour per visitor.`;
      note.hidden = false;
    }
  } catch {
    pill.dataset.state = "bad";
    $("health-text").textContent = "Server unreachable";
  }
}

function currentTheme() {
  const explicit = document.documentElement.dataset.theme;
  if (explicit) return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

$("theme-toggle").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("triagent-theme", next); } catch { /* storage unavailable */ }
});

// ------------------------------------------------------------------ wiring

function updateCount() {
  $("char-count").textContent = `${$("incident").value.length} / 8000`;
}

$("incident").addEventListener("input", updateCount);
$("load-demo").addEventListener("click", () => {
  $("incident").value = DEMO_INCIDENT;
  updateCount();
  $("incident").focus();
});
$("load-vague").addEventListener("click", () => {
  $("incident").value = VAGUE_INCIDENT;
  document.querySelector('input[name="mode"][value="agent"]').checked = true;
  updateCount();
  $("incident").focus();
});

$("triage-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const incident = $("incident").value.trim();
  if (incident.length < 10) {
    showError("Incident is too short", "Please enter at least 10 characters.");
    $("incident").focus();
    return;
  }
  submitTriage({ incident, mode: selectedMode() });
});

$("incident").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    $("triage-form").requestSubmit();
  }
});

$("clarify-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const clarification = $("clarification").value.trim();
  if (!clarification || !lastRequest) {
    $("clarification").focus();
    return;
  }
  submitTriage({ ...lastRequest, clarification });
});

// Deep link: /?sample=checkout|vague[&mode=no_retrieval|rag|agent] loads a sample and runs
// it, so a README or résumé link can open straight onto a finished report.
function runSampleFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const samples = { checkout: DEMO_INCIDENT, vague: VAGUE_INCIDENT };
  const incident = samples[params.get("sample")];
  if (!incident) return;
  const mode = params.get("mode") || "agent";
  const radio = document.querySelector(`input[name="mode"][value="${CSS.escape(mode)}"]`);
  if (radio) radio.checked = true;
  $("incident").value = incident;
  updateCount();
  submitTriage({ incident: incident.trim(), mode: selectedMode() });
}

updateCount();
loadHealth();
runSampleFromUrl();
