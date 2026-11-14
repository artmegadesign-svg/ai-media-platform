# MVP reliability audit — 2026-11-14

Baseline: `main` at `199d1a5f7333697143a48ef29458d01b00372aef`.
Scope: read-only inspection of the current orchestration, persistence, Telegram adapter, publisher, analytics, and existing tests. No production requests. Priority classifications are operational risk, not proof of incidents.

## Findings

| Priority | Finding and reproducible failure | Existing protection | Evidence / action |
| --- | --- | --- | --- |
| P1 (fixed in this PR) | One collector returns the same source URL twice in one batch; both items previously reached Intelligence, potentially triggering duplicate paid generation. | Previously persisted source keys were filtered. | `services/orchestration/mvp_cycle.py:74-81`; deduplicate source keys within the batch and test it. |
| P1 (open) | Two cycles query the same not-yet-persisted URL concurrently. Both see no Post, both enter generation, and one may later lose the unique-key race after paying for AI. | Post source-key uniqueness and conflict handling in `services/ai_engine/services/post_service.py:154-161` prevent duplicate persisted Posts, not duplicate AI spend. | `services/orchestration/mvp_cycle.py:74-81`; characterized by `test_concurrent_cycles_can_both_enter_ai_before_post_is_persisted`. Requires an agreed reservation/coordination design; do not add one implicitly. |
| P1 (open) | Generation succeeds externally but fails or process exits before Post commit; next run sees no persisted source and may pay again. | Existing persisted-source check only covers committed Posts. | `services/intelligence/content_generation_service.py:61-70`, `services/ai_engine/services/post_service.py:114-129`; characterized by `test_generation_failure_is_not_cached_between_cycle_invocations`. |
| P1 (operational) | Process dies after `pending -> publishing` claim and before result persistence. Record remains `publishing` and normal publisher intentionally does not retry it. | Atomic claim, explicit inspect/reconcile with operator evidence; no blind resend. | `services/publisher/publisher_service.py:90-115,194-209,226-238,240-299`; regression `test_crash_leaves_only_current_claim_unresolved`. Establish operator monitoring/reconciliation before unattended launch. |
| P1 (operational) | Telegram/Gateway accepts a message, but response is lost. Retrying the Telegram operation blindly may duplicate delivery. | Transport ambiguity maps to `unknown`, deterministic Idempotency-Key, and explicit reconciliation. | `services/publisher/adapters/telegram.py:20-30,119-178`, `services/publisher/publisher_service.py:135-169`; tests `test_transport_outcomes`, `test_unknown_reconciles_atomically_without_dispatch_or_false_failure`. |
| P2 | Post commit succeeds but post-generated Analytics recording fails; generated event may be absent. | Publication result events are transactional with publication status; post-generated event is separately best-effort. | `services/ai_engine/services/post_service.py:129-138`, `services/publisher/publisher_service.py:135-169`. Defer unless launch metrics depend on complete generation-event delivery. |

## Existing protections and tested behavior

- Publisher claims `pending` rows with a conditional UPDATE; parallel workers cannot both claim the same row. `services/publisher/publisher_service.py:90-98`; `tests/test_publisher_reliability.py::test_concurrent_claim_and_no_repeat_of_any_nonpending_state`.
- Provider calls occur outside live DB sessions; each result is persisted before claiming the next job. `tests/test_publisher_reliability.py::test_each_result_commits_before_next_claim_without_live_sessions`.
- DB result-write retries never resend to the provider. If persistence remains unconfirmed, `PublicationPersistenceError` is raised and the claim stays unresolved. `services/publisher/publisher_service.py:171-191`; `test_result_db_retry_never_repeats_http`, `test_actual_result_commit_failure_rolls_back_metric_and_status`.
- Publication status and Analytics event are written in one transaction, including `unknown`; analytics failure rolls back both. `services/publisher/publisher_service.py:135-169`; `test_analytics_failure_is_atomic_and_claim_failure_sends_nothing`.
- Telegram adapter distinguishes connection failure, uncertain transport result, HTTP ambiguity, and confirmed delivery with external message ID. `services/publisher/adapters/telegram.py:119-211`; `tests/test_publisher_reliability.py`.
- MVP cycle scopes publication to newly created Post IDs, avoiding unrelated pending backlog. `services/orchestration/mvp_cycle.py:34-43,84-93`; `tests/test_mvp_cycle.py`.

## Test coverage and launch recommendation

Tests cover mocked News/Intelligence/Content/Media-to-Publisher orchestration, scoped publishing, Telegram transport mapping, concurrent claims, persistence rollback, reconciliation and Analytics. These are component and integration tests, not proof of an unattended live SOURCE-to-ANALYTICS run.

Before claiming unattended production readiness: (1) decide cross-cycle AI reservation strategy with the main team, since changes to Intelligence/Generator are out of scope; (2) define alerting and evidence-based reconciliation for stuck `publishing`/`unknown` records; (3) run an owner-approved staging end-to-end dry run using mock providers. Do not auto-retry ambiguous Telegram delivery. No production deployment, paid AI calls, real Telegram sends or main merge were performed.

## Gateway boundary

AMP's Telegram adapter is inspected, not the separate `ai-gateway` implementation. Gateway-side deduplication guarantees and provider retry semantics cannot be certified from AMP code alone. Request a separate Gateway contract review before relying on end-to-end exactly-once delivery.
