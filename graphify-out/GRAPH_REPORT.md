# Graph Report - AI Triage Assisant System Project  (2026-11-12)

## Corpus Check
- 184 files · ~125,391 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 13 file(s) not represented in the graph (top: .jsonl 6, (none) 4, .example 1)

## Summary
- 1966 nodes · 4951 edges · 144 communities (122 shown, 22 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 515 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2d314a80`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- metrics.py
- FeedbackStore
- pytest
- workflow.py
- config.py
- test_model_tools.py
- gemini.py
- app.js
- Evidence
- run_eval.py
- MemoryStore
- test_llm_cache.py
- HashingEmbedder
- VectorStore
- test_corpus.py
- Settings
- redteam.py
- triage_stream
- valid_report
- test_retrieval_demo.py
- test_rerank.py
- test_integrations.py
- main
- build_dataset.py
- report.py
- test_streaming.py
- fake.py
- PostgresStore
- test_eval_metrics.py
- valid_report
- json
- train_qlora.py
- LLMCallError
- test_eval_judge.py
- test_pinned.py
- evaluate.py
- test_eval_run.py
- db
- Evaluation report: 20261110T042315Z-c9028c0
- streaming.py
- judge_calibration.py
- test_guards.py
- app/schemas.py
- test_finetune_data.py
- with
- AgentDecision
- alerts.py
- Retrieval: ingestion, embeddings, search
- Evaluation report: 20261110T024152Z-738ce87
- Evaluation report: 20261110T024152Z-738ce87
- alert_webhook
- slack.py
- test_observability.py
- load_cases
- README.md
- Evaluation
- Evaluation report: 20261109T235113Z-b466541
- eval/feedback.py
- test_api.py
- test_agent_api.py
- events.py
- build
- Triagent
- Security: prompt injection and output guards
- triage_and_post
- Retrieval evaluation: 20261110T020738Z-e23d4c3-retrieval
- ci.yml
- client
- LLMResult
- TriageResponse
- test_feedback.py
- Stage 4 (optional): QLoRA fine-tuning for severity classification
- check
- db
- Evaluation set
- Deploying the public demo
- jobs
- postgres
- test
- services
- Deduper
- RequestContextMiddleware
- Integrations: alert webhooks and Slack
- Observability
- QLoRA severity classifier: results
- Embedder
- verify_signature
- RB-DB-004.md
- RB-DEPLOY-001.md
- Reviewer feedback and the eval loop
- on
- INC-2025-014.md
- INC-2025-021.md
- INC-2025-033.md
- INC-2025-040.md
- INC-2026-003.md
- INC-2026-009.md
- INC-2026-011.md
- INC-2026-015.md
- INC-2026-022.md
- POL-ESC-001.md
- RB-APP-001.md
- RB-AUTH-001.md
- RB-CACHE-001.md
- RB-CDN-001.md
- RB-DB-001.md
- RB-DB-002.md
- RB-DB-003.md
- RB-K8S-001.md
- RB-K8S-002.md
- RB-NET-002.md
- RB-NET-003.md
- RB-PAY-001.md
- RB-TLS-001.md
- make_bundle.py
- _isolated_feedback_db
- app/feedback.py
- main.py
- test_gemini_live.py
- POL-SEV-001.md
- RateLimited
- deps.py
- settings
- CachingLLM
- triagent
- fake_retriever.py
- demo.py
- The knowledge corpus
- to_gemini_json_schema
- fakes.py
- load
- template
- test_live_gemini_on_demo_incident
- percentile

## God Nodes (most connected - your core abstractions)
1. `Settings` - 117 edges
2. `valid_report()` - 78 edges
3. `Evidence` - 65 edges
4. `TriageReport` - 57 edges
5. `TriageResponse` - 55 edges
6. `ScriptedLLM` - 49 edges
7. `FakeRetriever` - 44 edges
8. `LLMClient` - 40 edges
9. `MemoryStore` - 38 edges
10. `LLMResult` - 37 edges

## Surprising Connections (you probably didn't know these)
- `2. Embeddings: BGE is asymmetric` --references--> `HashingEmbedder`  [INFERRED]
  docs/retrieval.md → app/embeddings/hashing.py
- `agent (12)` --references--> `LLMCallError`  [INFERRED]
  eval/results/20261110T042315Z-c9028c0.md → app/llm/errors.py
- `Run metadata` --references--> `build_retriever()`  [INFERRED]
  eval/results/20261110T024152Z-738ce87.md → app/retrieval/factory.py
- `Run metadata` --references--> `build_retriever()`  [INFERRED]
  eval/results/20261110T042315Z-c9028c0.md → app/retrieval/factory.py
- `Run metadata` --references--> `build_retriever()`  [INFERRED]
  eval/results/example-smoke.md → app/retrieval/factory.py

## Import Cycles
- None detected.

## Communities (144 total, 22 thin omitted)

### Community 0 - "metrics.py"
Cohesion: 0.13
Nodes (22): abstention(), abstained(), citation_precision(), citation_validity(), cited_ids(), claim_support(), clarification(), cluster_units() (+14 more)

### Community 1 - "FeedbackStore"
Cohesion: 0.19
Nodes (10): FeedbackStore, record(), response(), reviewed(), test_cli_end_to_end(), test_eviction_drops_oldest_unreviewed_first(), test_export_turns_feedback_into_valid_cases(), test_last_verdict_wins_for_the_same_incident() (+2 more)

### Community 2 - "pytest"
Cohesion: 0.16
Nodes (8): BudgetedLLM, DailyBudget, with_cache(), demo_client(), Out, test_cache_hits_do_not_spend_the_budget(), test_daily_budget_resets_at_utc_midnight(), test_factory_wraps_cache_then_budget_in_demo_mode()

### Community 3 - "workflow.py"
Cohesion: 0.13
Nodes (18): _blocked_actions(), _decide(), _draft(), _enforce(), _normalise_query(), _override(), _respond(), _retrieve() (+10 more)

### Community 4 - "config.py"
Cohesion: 0.14
Nodes (5): get_settings(), main(), main(), main(), render()

### Community 5 - "test_model_tools.py"
Cohesion: 0.16
Nodes (16): render(), client_with(), ok_body(), summary(), test_api_key_is_sent_as_bearer_only_when_set(), test_client_errors_are_not_retried(), test_comparison_flags_mismatched_cases(), test_comparison_table_and_warnings() (+8 more)

### Community 6 - "gemini.py"
Cohesion: 0.14
Nodes (4): GeminiClient, is_retryable(), parse_json(), 7. The HTTP contract

### Community 7 - "app.js"
Cohesion: 0.11
Nodes (36): chips(), citedIds(), describeStep(), el(), emptyItem(), ERROR_TITLES, errorDetail(), finish() (+28 more)

### Community 8 - "Evidence"
Cohesion: 0.10
Nodes (22): build_decide_user_prompt(), build_repair_user_prompt(), format_evidence_summary(), _neutralise(), _snippet(), merge_evidence(), _attr(), build_no_retrieval_user_prompt() (+14 more)

### Community 9 - "run_eval.py"
Cohesion: 0.11
Nodes (16): LLMClient, build_llm(), build_judge_llm(), EvalSettings, judge_model_name(), _cache_hits(), _git(), git_info() (+8 more)

### Community 10 - "MemoryStore"
Cohesion: 0.08
Nodes (18): chunk_document(), content_hash(), estimate_tokens(), Chunk, IndexNotFoundError, MemoryStore, test_content_prefix_and_preamble_dropped(), test_crlf_body_gives_identical_chunks() (+10 more)

### Community 11 - "test_llm_cache.py"
Cohesion: 0.26
Nodes (11): call(), CountingLLM, Other, Out, test_any_input_change_is_a_miss(), test_cache_survives_a_new_wrapper(), test_corrupt_entry_is_a_miss_and_gets_rewritten(), test_errors_are_not_cached() (+3 more)

### Community 12 - "HashingEmbedder"
Cohesion: 0.09
Nodes (10): l2_normalise(), HashingEmbedder, tokenize(), BM25Index, test_hashing_empty_text_is_zero_vector(), test_hashing_is_deterministic_and_normalised(), test_hashing_prefers_token_overlap(), test_l2_normalise_handles_zero_rows() (+2 more)

### Community 13 - "VectorStore"
Cohesion: 0.11
Nodes (4): ingest(), IngestStats, VectorStore, 8. Memory vs Postgres

### Community 14 - "test_corpus.py"
Cohesion: 0.08
Nodes (18): CorpusError, load_corpus(), normalise_newlines(), parse_document(), _chunk_ids(), _headings(), _load_cases(), _parse() (+10 more)

### Community 15 - "Settings"
Cohesion: 0.12
Nodes (23): Settings, build_embedder(), build_retriever(), with_reranker(), rrf_fuse(), build_store(), main(), run() (+15 more)

### Community 16 - "redteam.py"
Cohesion: 0.15
Nodes (14): Attack, compromised_reply(), reply(), evaluate(), goal_met(), live(), load_attacks(), main() (+6 more)

### Community 17 - "triage_stream"
Cohesion: 0.20
Nodes (5): health(), post_feedback(), remember(), triage(), triage_stream()

### Community 18 - "valid_report"
Cohesion: 0.21
Nodes (25): ScriptedLLM, 2. The state machine, ask(), by_query(), draft(), names(), overrides(), rewrite() (+17 more)

### Community 19 - "test_retrieval_demo.py"
Cohesion: 0.10
Nodes (7): SearchRetriever, Evidence, _best_rank(), retriever(), test_demo_incident_top5_contains_runbook_and_past_incident(), test_query_prefix_applied_once(), test_vector_ranks_db_runbook_above_dns_runbook()

### Community 20 - "test_rerank.py"
Cohesion: 0.09
Nodes (14): FastEmbedReranker, passage_text(), RerankingRetriever, VariantRetriever, KeywordReranker, ListRetriever, test_empty_query_or_k_returns_nothing(), test_k_larger_than_candidates_widens_pool_to_k() (+6 more)

### Community 21 - "test_integrations.py"
Cohesion: 0.13
Nodes (18): all_text(), configure(), response_for(), signed(), slash_body(), test_alert_storm_is_rate_limited(), test_health_reports_integrations_without_secrets(), test_insufficient_evidence_and_clarification() (+10 more)

### Community 22 - "main"
Cohesion: 0.17
Nodes (10): Reranker, aggregate(), evaluate(), _fmt(), is_scored(), main(), primary_doc(), render() (+2 more)

### Community 23 - "build_dataset.py"
Cohesion: 0.18
Nodes (15): _error_for(), Facts, fmt_errors(), fmt_latency(), impact(), _internal_text(), jaccard(), leakage_report() (+7 more)

### Community 24 - "report.py"
Cohesion: 0.16
Nodes (14): compute_all(), failures(), _confusion(), _failure_detail(), fmt_mean_pct(), fmt_rate(), _get(), _metadata() (+6 more)

### Community 25 - "test_streaming.py"
Cohesion: 0.21
Nodes (9): client(), names(), stream(), test_agent_streams_decide_and_draft(), test_final_result_matches_plain_endpoint(), test_provider_failure_is_a_terminal_error_event(), generate_json(), test_rag_events_arrive_in_pipeline_order() (+1 more)

### Community 26 - "fake.py"
Cohesion: 0.12
Nodes (11): DemoLLM, LLMCall, minimal_instance(), _to_result(), _trivial_value(), test_main_bad_case_id_is_setup_error(), test_main_end_to_end_writes_parseable_files(), test_main_records_retriever_build_failure_per_case() (+3 more)

### Community 27 - "PostgresStore"
Cohesion: 0.07
Nodes (9): Cause, Document, NextStep, IndexMismatchError, PostgresStore, _fill(), store(), test_roundtrip_search_and_delete() (+1 more)

### Community 28 - "test_eval_metrics.py"
Cohesion: 0.14
Nodes (16): RetrievedRef, ClaimJudgement, _claim(), result(), test_abstention_rates_and_ambiguous_excluded(), test_citation_precision_proxy(), test_claim_support_shares_and_unjudged(), test_clarification_and_over_asking_agent_only() (+8 more)

### Community 29 - "valid_report"
Cohesion: 0.13
Nodes (20): TriageRequest, incident_text(), run_triage(), queries_for(), call(), main(), sample_incidents(), FakeRetriever (+12 more)

### Community 30 - "json"
Cohesion: 0.11
Nodes (30): TriageReport, Violation, _cited(), _inconsistent_abstention(), _missing_citations(), _parse(), _unknown_citations(), validate_report() (+22 more)

### Community 31 - "train_qlora.py"
Cohesion: 0.17
Nodes (8): chat_prompt(), label_token_ids(), load_split(), score_labels(), collate(), encode(), main(), ds()

### Community 32 - "LLMCallError"
Cohesion: 0.20
Nodes (3): LLMCallError, LLMConfigError, OpenAICompatClient

### Community 33 - "test_eval_judge.py"
Cohesion: 0.23
Nodes (12): extract_claims(), judge_response(), JudgeOutcome, JudgeOutput, JudgeVerdict, _response(), test_bad_or_partial_judge_output_is_recorded_as_unjudged(), test_extract_claims_numbers_causes_then_steps() (+4 more)

### Community 34 - "test_pinned.py"
Cohesion: 0.22
Nodes (11): _load_pinned(), pinned_evidence(), with_pinned(), run_rag(), settings(), test_no_pinned_docs_configured(), test_pinned_evidence_loads_every_policy_section(), test_rag_can_cite_policy_even_when_search_misses_it() (+3 more)

### Community 35 - "evaluate.py"
Cohesion: 0.18
Nodes (11): is_boundary(), main(), metrics(), paired_diff_ci(), render(), ci(), pct(), run() (+3 more)

### Community 36 - "test_eval_run.py"
Cohesion: 0.18
Nodes (13): _agent_response(), _case(), no_dotenv(), settings(), test_agent_clarification_is_resubmitted_and_final_response_scored(), fake_run(), test_agent_clarifies_ambiguous_case_then_is_scored(), test_fake_retriever_serves_real_chunk_ids() (+5 more)

### Community 37 - "db"
Cohesion: 0.12
Nodes (16): environment, healthcheck, image, ports, volumes, POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER (+8 more)

### Community 38 - "Evaluation report: 20261110T042315Z-c9028c0"
Cohesion: 0.12
Nodes (16): agent, agent (12), ambiguous, answerable, By category, Comparison, Evaluation report: 20261110T042315Z-c9028c0, Failed and erroring cases (+8 more)

### Community 39 - "streaming.py"
Cohesion: 0.17
Nodes (7): DemoCacheMiss, work(), error_status(), sse(), stream_triage(), put(), run()

### Community 40 - "judge_calibration.py"
Cohesion: 0.17
Nodes (13): binary(), cohens_kappa(), export(), judged_claims(), kappa_words(), load_labels(), main(), render() (+5 more)

### Community 41 - "test_guards.py"
Cohesion: 0.18
Nodes (16): build_guards(), check(), OutputGuards, _severity_provenance(), _texts(), _words(), guards_for(), guards() (+8 more)

### Community 42 - "app/schemas.py"
Cohesion: 0.19
Nodes (3): build_judge_prompt(), Claim, _neutralise()

### Community 43 - "test_finetune_data.py"
Cohesion: 0.12
Nodes (6): label(), F(), test_committed_data_is_current(), test_every_label_matches_its_facts(), test_label_follows_policy_clauses(), test_label_tokens_share_a_prefix()

### Community 44 - "with"
Cohesion: 0.19
Nodes (16): steps, STORE_BACKEND, steps, steps, env, if, name, run (+8 more)

### Community 45 - "AgentDecision"
Cohesion: 0.12
Nodes (9): AgentDecision, 1. The model decides, the application enforces, 3. Failure handling, 4. Cost and latency bounds, 5. Why one clarifying round-trip, 6. How the trace powers the demo and the eval, 7. Known limitations, 8. Design FAQ (+1 more)

### Community 46 - "alerts.py"
Cohesion: 0.25
Nodes (9): _alert_lines(), _fingerprint(), from_alertmanager(), from_generic(), Incident, parse(), test_alertmanager_payload_becomes_one_incident_of_firing_alerts(), test_generic_payload_and_unknown_shape() (+1 more)

### Community 47 - "Retrieval: ingestion, embeddings, search"
Cohesion: 0.14
Nodes (14): 10. Design FAQ, 1. Chunking: one chunk per `## ` section, 2. Embeddings: BGE is asymmetric, 3. Normalisation and cosine, 4. Why no ANN index, 5. BM25 vs vectors, 6. Hybrid: Reciprocal Rank Fusion, 7. Idempotent, incremental ingestion (+6 more)

### Community 48 - "Evaluation report: 20261110T024152Z-738ce87"
Cohesion: 0.13
Nodes (14): agent, ambiguous, answerable, By category, Comparison, Evaluation report: 20261110T024152Z-738ce87, Failed and erroring cases, How to read this (+6 more)

### Community 49 - "Evaluation report: 20261110T024152Z-738ce87"
Cohesion: 0.13
Nodes (14): agent, ambiguous, answerable, By category, Comparison, Evaluation report: 20261110T024152Z-738ce87, Failed and erroring cases, How to read this (+6 more)

### Community 50 - "alert_webhook"
Cohesion: 0.23
Nodes (5): alert_webhook(), get_notifier(), _limiter(), slack_command(), is_slack_response_url()

### Community 51 - "slack.py"
Cohesion: 0.29
Nodes (7): _cites(), _clip(), _context(), escape(), format_report(), _section(), slash_ack()

### Community 52 - "test_observability.py"
Cohesion: 0.07
Nodes (14): configure_logging(), estimate_cost(), JsonFormatter, _RequestIdFilter, set_tracer(), TextFormatter, client(), sample() (+6 more)

### Community 53 - "load_cases"
Cohesion: 0.10
Nodes (17): load_cases(), sha256_dir(), sha256_file(), _case(), test_duplicate_ids_raise(), test_filter_by_ids_and_limit(), test_hashes_are_stable_and_content_sensitive(), test_inconsistent_labels_raise() (+9 more)

### Community 54 - "README.md"
Cohesion: 0.16
Nodes (6): Confusion matrix (rows: judge, columns: claude-opus-5-5), Disagreements, LLM judge vs claude-opus-5-5 labels, Model comparison (agent mode), Model comparison (rag mode), Notes

### Community 55 - "Evaluation"
Cohesion: 0.13
Nodes (15): 10. Comparing models, 11. Growing the eval set from reviewer feedback, 1. What is compared, and why the same model, 2. Metrics: definition and what each does NOT measure, 3. LLM-as-judge pitfalls, 4. Small-n statistics and bootstrap CIs, 5. The ambiguous-case asymmetry, 6. Data leakage and other threats to validity (+7 more)

### Community 56 - "Evaluation report: 20261109T235113Z-b466541"
Cohesion: 0.14
Nodes (13): agent, ambiguous, answerable, By category, Comparison, Evaluation report: 20261109T235113Z-b466541, Failed and erroring cases, How to read this (+5 more)

### Community 57 - "eval/feedback.py"
Cohesion: 0.21
Nodes (9): EvalCase, export_cases(), main(), _norm(), _pct(), render(), summarize(), to_case() (+1 more)

### Community 58 - "test_api.py"
Cohesion: 0.12
Nodes (14): ServiceUnavailable, client(), test_health_when_index_missing(), broken(), test_invalid_output_returns_422_with_full_response(), test_no_retrieval_works_without_an_index(), broken(), test_real_dependencies_without_key_return_503() (+6 more)

### Community 59 - "test_agent_api.py"
Cohesion: 0.24
Nodes (8): client(), post_agent(), test_agent_ok_returns_200_with_trace(), test_demo_llm_agent_end_to_end(), test_invalid_after_repair_is_422_with_full_response(), test_needs_clarification_is_200_with_question(), test_resubmit_with_clarification_cannot_ask_again(), use_llm()

### Community 60 - "events.py"
Cohesion: 0.16
Nodes (7): emit(), evidence(), listening(), step_done(), step_started(), Design decisions, test_emit_without_listener_is_a_no_op_and_listeners_nest()

### Community 61 - "build"
Cohesion: 0.20
Nodes (8): build(), build_prompt(), generate(), main(), policy_text(), built(), test_build_is_deterministic(), test_policy_text_is_the_corpus_document()

### Community 62 - "Triagent"
Cohesion: 0.11
Nodes (18): Alert webhooks and Slack, Architecture, Continuous integration, Deployment, End-to-end (no_retrieval vs RAG vs agent), Fine-tuning a small model (QLoRA), Hosted model vs a local 3B model, Known limitations (+10 more)

### Community 63 - "Security: prompt injection and output guards"
Cohesion: 0.18
Nodes (9): Defenses, in order, Measurement: worst-case model, Not covered, Residual risk, Security: prompt injection and output guards, Slack output, Threat model, Prompt-injection red team (worst-case model) (+1 more)

### Community 64 - "triage_and_post"
Cohesion: 0.29
Nodes (4): _deliver(), _error_message(), triage_and_post(), SlackNotifier

### Community 65 - "Retrieval evaluation: 20261110T020738Z-e23d4c3-retrieval"
Cohesion: 0.20
Nodes (9): Caveats, Chunk recall@k by slice, Doc recall@k by slice, MRR (chunk level) by slice, Not scored (nothing case-specific to retrieve), Overall, Primary-doc hit@k by slice, Primary doc rank per case (+1 more)

### Community 66 - "ci.yml"
Cohesion: 0.20
Nodes (9): concurrency, cancel-in-progress, group, env, LLM_PROVIDER, PIP_DISABLE_PIP_VERSION_CHECK, name, permissions (+1 more)

### Community 67 - "client"
Cohesion: 0.22
Nodes (5): reset_state(), client(), notifier(), RecordingNotifier, test_slack_outage_does_not_break_the_webhook()

### Community 68 - "LLMResult"
Cohesion: 0.19
Nodes (5): OfflineLLM, LLMResult, Counting, test_key_free_demo_never_needs_a_provider(), generate_json()

### Community 69 - "TriageResponse"
Cohesion: 0.15
Nodes (6): _triage(), export_spans(), _get_tracer(), record_triage(), summarize(), TriageResponse

### Community 70 - "test_feedback.py"
Cohesion: 0.14
Nodes (6): _cached_feedback_store(), get_feedback_store(), get_settings(), client(), store(), test_feedback_can_be_disabled()

### Community 71 - "Stage 4 (optional): QLoRA fine-tuning for severity classification"
Cohesion: 0.22
Nodes (9): Dataset requirements, Design FAQ, Go/no-go criteria, Hardware requirements, Running it (free), Stage 4 (optional): QLoRA fine-tuning for severity classification, The question the experiment answers, What was built (+1 more)

### Community 72 - "check"
Cohesion: 0.46
Nodes (5): check(), overall(), test_missing_metric_fails(), test_one_primary_miss_in_25_is_tolerated_two_are_not(), test_passes_at_or_above_every_threshold()

### Community 73 - "db"
Cohesion: 0.25
Nodes (8): env, image, options, ports, POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER, db

### Community 74 - "Evaluation set"
Cohesion: 0.29
Nodes (6): Categories, Evaluation set, Fields, How chunk IDs are derived, Labelling rubric, Limitations

### Community 75 - "Deploying the public demo"
Cohesion: 0.29
Nodes (6): Deep links, Deploying the public demo, Option A: Render (recommended; deploys from GitHub), Option B: Hugging Face Spaces (Docker), Running the container locally, What protects the API key

### Community 76 - "jobs"
Cohesion: 0.29
Nodes (7): name, runs-on, jobs, docker, retrieval, name, runs-on

### Community 77 - "postgres"
Cohesion: 0.29
Nodes (7): DATABASE_URL, REQUIRE_POSTGRES, postgres, env, name, runs-on, services

### Community 78 - "test"
Cohesion: 0.29
Nodes (7): test, python, fail-fast, matrix, name, runs-on, strategy

### Community 79 - "services"
Cohesion: 0.29
Nodes (6): services, healthCheckPath, name, plan, runtime, type

### Community 80 - "Deduper"
Cohesion: 0.40
Nodes (3): Deduper, _deduper(), test_deduper_expires()

### Community 82 - "Integrations: alert webhooks and Slack"
Cohesion: 0.33
Nodes (5): Alert sources, Design decisions, Integrations: alert webhooks and Slack, Metrics, Try it locally, free

### Community 83 - "Observability"
Cohesion: 0.33
Nodes (5): Metrics: `GET /metrics` (Prometheus), Observability, Request ids, Structured logs, Traces: OpenTelemetry (optional)

### Community 84 - "QLoRA severity classifier: results"
Cohesion: 0.33
Nodes (6): Accuracy by test template, Confusion matrix: Base (rows: gold, columns: predicted), Confusion matrix: QLoRA (rows: gold, columns: predicted), QLoRA severity classifier: results, Reading the result, Training

### Community 86 - "verify_signature"
Cohesion: 0.60
Nodes (4): _check_token(), sign(), verify_signature(), test_signature_check()

### Community 87 - "RB-DB-004.md"
Cohesion: 0.40
Nodes (4): Diagnosis, Mitigation, Prevention, Symptoms

### Community 88 - "RB-DEPLOY-001.md"
Cohesion: 0.40
Nodes (4): Caveats, Procedure, Verification, When to roll back

### Community 89 - "Reviewer feedback and the eval loop"
Cohesion: 0.40
Nodes (5): Design decisions, Limits, Reviewer feedback and the eval loop, Using it, What a reviewer does

### Community 90 - "on"
Cohesion: 0.40
Nodes (5): on, pull_request, push, workflow_dispatch, branches

### Community 91 - "INC-2025-014.md"
Cohesion: 0.50
Nodes (3): Resolution and follow-ups, Root cause, Summary

### Community 92 - "INC-2025-021.md"
Cohesion: 0.50
Nodes (3): Resolution and follow-ups, Root cause, Summary

### Community 93 - "INC-2025-033.md"
Cohesion: 0.50
Nodes (3): Resolution and follow-ups, Root cause, Summary

### Community 94 - "INC-2025-040.md"
Cohesion: 0.50
Nodes (3): Resolution and follow-ups, Root cause, Summary

### Community 95 - "INC-2026-003.md"
Cohesion: 0.50
Nodes (3): Resolution and follow-ups, Root cause, Summary

### Community 96 - "INC-2026-009.md"
Cohesion: 0.50
Nodes (3): Resolution and follow-ups, Root cause, Summary

### Community 97 - "INC-2026-011.md"
Cohesion: 0.50
Nodes (3): Resolution and follow-ups, Root cause, Summary

### Community 98 - "INC-2026-015.md"
Cohesion: 0.50
Nodes (3): Resolution and follow-ups, Root cause, Summary

### Community 99 - "INC-2026-022.md"
Cohesion: 0.50
Nodes (3): Resolution and follow-ups, Root cause, Summary

### Community 100 - "POL-ESC-001.md"
Cohesion: 0.50
Nodes (3): Escalation, Paging by severity, Third-party dependencies

### Community 101 - "RB-APP-001.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 102 - "RB-AUTH-001.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 103 - "RB-CACHE-001.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 104 - "RB-CDN-001.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 105 - "RB-DB-001.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 106 - "RB-DB-002.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 107 - "RB-DB-003.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 108 - "RB-K8S-001.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 109 - "RB-K8S-002.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 110 - "RB-NET-002.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 111 - "RB-NET-003.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 112 - "RB-PAY-001.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 113 - "RB-TLS-001.md"
Cohesion: 0.50
Nodes (3): Diagnosis, Mitigation, Symptoms

### Community 116 - "app/feedback.py"
Cohesion: 0.16
Nodes (6): cited_ids(), FeedbackIn, prompt_versions(), UnknownTriage, Severity, test_unknown_triage_is_refused()

### Community 117 - "main.py"
Cohesion: 0.22
Nodes (5): _demo_cache_miss(), _llm_failed(), metrics(), _rate_limited(), _service_unavailable()

### Community 119 - "test_gemini_live.py"
Cohesion: 0.31
Nodes (9): call(), FakeModels, make_client(), response(), test_bad_json_returns_parsed_none_instead_of_raising(), test_does_not_retry_client_errors(), test_gives_up_after_two_retries(), test_parses_json_and_records_tokens_and_config() (+1 more)

### Community 121 - "RateLimited"
Cohesion: 0.22
Nodes (5): RateLimited, SlidingWindowLimiter, Clock, test_limiter_blocks_after_limit_and_reopens_after_window(), test_rejected_hits_are_not_recorded()

### Community 122 - "deps.py"
Cohesion: 0.23
Nodes (6): _cached_llm(), _cached_retriever(), get_llm(), get_retriever(), get_retriever_provider(), Retriever

### Community 124 - "CachingLLM"
Cohesion: 0.27
Nodes (3): cache_key(), CachingLLM, test_model_and_extra_key_are_part_of_the_key()

### Community 134 - "fake_retriever.py"
Cohesion: 0.25
Nodes (3): KeywordOverlapRetriever, load_corpus_chunks(), _tokens()

### Community 135 - "demo.py"
Cohesion: 0.20
Nodes (3): client_key(), demo_rate_limit(), test_client_key()

### Community 136 - "The knowledge corpus"
Cohesion: 0.20
Nodes (8): Doc index, Format, Rules for editing, The knowledge corpus, Three doc types, three jobs, Why deliberately uncovered topics, Why near-miss distractors, doc_id()

### Community 137 - "to_gemini_json_schema"
Cohesion: 0.40
Nodes (3): _clean(), to_gemini_json_schema(), test_gemini_schema_has_no_unsupported_keywords_and_requires_all()

## Knowledge Gaps
- **1 isolated node(s):** `triagent`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 769 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Settings` connect `Settings` to `pytest`, `workflow.py`, `config.py`, `test_model_tools.py`, `run_eval.py`, `test_llm_cache.py`, `HashingEmbedder`, `test_live_gemini_on_demo_incident`, `redteam.py`, `valid_report`, `test_retrieval_demo.py`, `test_integrations.py`, `main`, `test_streaming.py`, `valid_report`, `test_eval_judge.py`, `test_pinned.py`, `test_eval_run.py`, `test_guards.py`, `app/schemas.py`, `alert_webhook`, `test_observability.py`, `load_cases`, `eval/feedback.py`, `test_api.py`, `test_agent_api.py`, `triage_and_post`, `client`, `LLMResult`, `TriageResponse`, `test_feedback.py`, `Deduper`, `Embedder`, `verify_signature`, `test_gemini_live.py`, `deps.py`, `settings`?**
  _High betweenness centrality (0.104) - this node is a cross-community bridge._
- **Are the 55 inferred relationships involving `Settings` (e.g. with `_Run` and `run_agent()`) actually correct?**
  _`Settings` has 55 INFERRED edges - model-reasoned connections that need verification._
- **What connects `triagent` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `metrics.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12802275960170698 - nodes in this community are weakly interconnected._
- **Why does `Streaming progress: `POST /triage/stream`` connect `app.js` to `events.py`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 27 inferred relationships involving `Evidence` (e.g. with `build_decide_user_prompt()` and `build_repair_user_prompt()`) actually correct?**
  _`Evidence` has 27 INFERRED edges - model-reasoned connections that need verification._
- **Should `workflow.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12685560053981107 - nodes in this community are weakly interconnected._