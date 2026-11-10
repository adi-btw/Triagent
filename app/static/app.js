// Demo UI for POST /triage. Vanilla JS, no build step, no external dependencies.
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

const $ = (id) => document.getElementById(id);

// The last request sent, so a clarification can resubmit the same incident and mode.
let lastRequest = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined) {
      node.append(child instanceof Node ? child : String(child));
    }
  }
  return node;
}

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function setBusy(busy) {
  for (const button of document.querySelectorAll("button")) button.disabled = busy;
  $("submit").textContent = busy ? "Triaging..." : "Triage";
}

function showError(title, detail) {
  const box = $("error");
  box.replaceChildren(el("strong", { text: title }));
  if (detail) box.append(el("div", { text: detail }));
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
      renderResponse(body);
      return;
    }
    $("result").hidden = true;
    const titles = {
      422: "The request was rejected",
      501: "This mode is not available on the server",
      502: "The language model provider failed",
      503: "The server is not fully configured",
    };
    showError(titles[resp.status] || `Request failed (HTTP ${resp.status})`, errorDetail(body));
  } catch (err) {
    $("result").hidden = true;
    showError("Could not reach the server", String(err));
  } finally {
    setBusy(false);
  }
}

// ------------------------------------------------------------------ rendering

function renderResponse(body) {
  const evidenceIds = new Set((body.evidence || []).map((e) => e.chunk_id));
  const report = body.report;

  const badge = $("status-badge");
  badge.className = `badge ${body.status}`;
  badge.textContent = body.status.replaceAll("_", " ");

  $("severity").textContent = report ? `Severity: ${report.severity || "unknown"}` : "";
  if (report && report.severity_citations.length) {
    $("severity").append(" ", chips(report.severity_citations, evidenceIds));
  }

  renderClarification(body);
  renderReport(report, evidenceIds);
  renderViolations(body.trace.violations);
  renderTimeline(body.trace.steps);
  renderEvidence(body.evidence || []);
  renderFooter(body.trace);

  $("result").hidden = false;
}

function renderClarification(body) {
  const needed = body.status === "needs_clarification";
  $("clarify").hidden = !needed;
  if (needed) {
    $("clarify-question").textContent = body.clarifying_question;
    $("clarification").value = "";
    $("clarification").focus();
  }
}

function renderReport(report, evidenceIds) {
  $("report-body").hidden = !report;
  if (!report) return;
  $("summary").textContent = report.summary;
  $("abstain").hidden = !report.insufficient_evidence;

  const causes = report.likely_causes.map((c) =>
    el("li", {}, el("span", { class: "confidence", text: c.confidence }), c.description,
      chips(c.citations, evidenceIds)));
  $("causes").replaceChildren(...(causes.length ? causes : [emptyItem("None stated.")]));

  const steps = report.next_steps.map((s) =>
    el("li", {}, s.action, chips(s.citations, evidenceIds)));
  $("steps").replaceChildren(...(steps.length ? steps : [emptyItem("None stated.")]));

  $("missing-wrap").hidden = !report.missing_information.length;
  $("missing").replaceChildren(...report.missing_information.map((m) => el("li", { text: m })));
}

function emptyItem(text) {
  return el("li", { class: "empty muted", text });
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
  setTimeout(() => details.classList.remove("flash"), 1200);
  details.scrollIntoView({ behavior: "smooth", block: "center" });
  details.querySelector("summary").focus({ preventScroll: true });
}

function renderViolations(violations) {
  $("violations-wrap").hidden = !violations.length;
  $("violations").replaceChildren(...violations.map((v) =>
    el("li", {}, el("code", { text: v.type }), ": ", v.detail)));
}

function renderEvidence(evidence) {
  const items = evidence.map((e) =>
    el("details", { "data-id": e.chunk_id },
      el("summary", {}, el("code", { text: e.chunk_id }), ` ${e.title} / ${e.heading} `,
        el("span", { class: "score", text: e.method === "pinned" ? "always included" : `score ${e.score.toFixed(3)}` })),
      el("pre", { text: e.content })));
  $("evidence").replaceChildren(
    ...(items.length ? items : [el("p", { class: "muted", text: "No evidence retrieved." })]));
}

function renderFooter(trace) {
  const t = trace.timings_ms || {};
  const fmt = (k) => (k in t ? `${k} ${Math.round(t[k])} ms` : null);
  const parts = ["retrieval", "generation", "validation", "total"].map(fmt).filter(Boolean);
  $("footer").textContent =
    `${parts.join(" · ")} · LLM calls: ${trace.llm_calls} · model: ${trace.model} · mode: ${trace.mode}`;
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
      return `“${truncate(d.query, 80)}” → ${(d.results || []).length} chunks${added}`;
    }
    case "decide":
      return d.decision ? `${d.decision}: ${d.rationale}` : `malformed output (${truncate(d.error)})`;
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
      return `${fed}${d.parsed_json === false ? "output was not JSON" : "JSON report"}` +
        (d.output_tokens != null ? `, ~${d.output_tokens} output tokens` : "");
    }
    case "validate": {
      const n = (d.violations || []).length;
      const verdict = n ? `${n} violation(s)` : "passed";
      const repair = d.repair ? `; repair ${d.repair}` : "";
      return `${verdict} against ${(d.allowed_ids || []).length} allowed ids${repair}`;
    }
    default:
      return truncate(JSON.stringify(d));
  }
}

function renderTimeline(steps) {
  $("timeline").replaceChildren(...steps.map((step) => {
    const failed = step.name === "validate" && (step.detail.violations || []).length;
    const cls = step.name === "override" ? "override" : failed ? "fail" : "";
    return el("li", { class: cls },
      el("span", { class: "step-name", text: step.name }),
      el("span", { class: "step-latency", text: `${step.latency_ms.toFixed(1)} ms` }),
      el("span", { class: "step-detail", text: describeStep(step) }));
  }));
}

// ------------------------------------------------------------------ wiring

$("load-demo").addEventListener("click", () => { $("incident").value = DEMO_INCIDENT; });
$("load-vague").addEventListener("click", () => {
  $("incident").value = VAGUE_INCIDENT;
  document.querySelector('input[name="mode"][value="agent"]').checked = true;
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

$("clarify-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const clarification = $("clarification").value.trim();
  if (!clarification || !lastRequest) {
    $("clarification").focus();
    return;
  }
  submitTriage({ ...lastRequest, clarification });
});
