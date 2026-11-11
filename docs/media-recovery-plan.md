# Stage B technical plan — not implemented

This is a proposal for separate approval. PR #26's caption continuation does not
implement retries, generation claims, new runtime states, or recovery scheduling.

## Priority 1: prevent repeated paid generation

The invariant is at most one automatic outbound image-generation request per
persisted material, shared by RU/EN. `ready` idempotency alone is insufficient:
timeouts, storage failures, result-commit failures and concurrent calls can all
leave an upstream-paid result unrecorded locally.

1. In `MediaPlanningService`, serialize neutral-image planning on the existing
   Post row and reuse its existing image plan. Do not create a second plan during
   recovery. Respect already-ready images and any recorded generation attempt.
2. In `MediaGenerationService` / `MediaAssetRepository`, atomically reserve the
   attempt in a short database transaction, committing before the HTTP call.
   Use a conditional update/claim token so exactly one caller wins. A claim also
   records the attempt count and start time in existing JSON metadata. Planning
   must not create another asset that bypasses this reservation for the same Post.
3. Release the transaction before network I/O. On success, store the ready result
   only if the same claim still owns the attempt. Retain claim/audit evidence.
4. On timeout, failure after dispatch, crash, or uncertain result persistence,
   retain an unresolved attempt and prohibit automatic regeneration. Do not turn
   an expired claim into permission to send again. A crash before dispatch may
   sacrifice a generation rather than risk paying twice.
5. For pre-existing failed/ambiguous plans without reliable attempt history,
   require explicit reconciliation; do not assume zero previous paid requests.

This provides an at-most-one automatic attempt, not guaranteed exactly-once
upstream execution or guaranteed image delivery. The Gateway has no image-request
idempotency contract available to AMP; no Gateway change is proposed. All network
outcomes remain distinct from whether the database write was confirmed.

## Priority 2: explicit search completion

In `RSSNewsCollector`, distinguish successful image discovery from an incomplete
lookup, transient transport/429/5xx failure, permanent HTTP rejection, malformed
or oversized data, and an HTTP-200 error/challenge document. Validate response
content before interpreting an empty extraction as absence. Do not bypass access
controls. Keep independently valid licensed RSS candidates usable during a page
outage. A failed feed must not erase pending work or be interpreted as a negative
image lookup.

In `MediaResolver`, allow an executable AI fallback only for a confirmed completed
lookup with no suitable permitted official candidate. `not_checked`, missing
status and incomplete/error results must not authorize paid generation. Preserve
rights denials and provenance; absence of permission is different from a network
failure. Record the source identifier as well as the original/canonical page URL
so a deferred plan can be rediscovered without relying on a current RSS entry.

## Priority 3: bounded recovery in existing services

Add an operation to the existing content/media services to recheck a single stored
source URL through its existing official collector. Update the same MediaAsset.
`MediaAssetRepository` selects due work; existing JSON metadata stores counters,
next-check time, safe error category and claim ownership. Do not introduce a queue,
new worker subsystem or a parallel publisher.

Proposed defaults for approval: three additional source checks after 1, 5 and 30
minutes, with a bounded batch per MVP invocation. Claim due work atomically and
reject stale responses from earlier claims. These retries are read-only source
checks, not generation retries. On exhausted transient errors, stop source
retries and do not infer confirmed absence or start paid generation; use an
explicit terminal/manual-review policy (text-only publication can be approved
separately). Successful negative discovery may enter the single-attempt generation
path only if no paid attempt has ever been reserved for this material.

Invoke recovery independently of the new-news source-key deduplication in the
existing `run_mvp_cycle`. No background scheduling is currently present: automatic
progress occurs on later invocations of that existing cycle. Runtime/deployment
scheduling remains outside this code change.

## Priority 4: publication safety

Use the existing Publisher claim mechanism. While media discovery is deferred,
keep affected ChannelContent pending and do not dispatch a premature text-only
message. After media is ready or an explicitly approved terminal fallback applies,
pass only the relevant pending publication IDs/posts to the existing Publisher.
Never reset published, publishing, unknown or failed publications automatically.
A post already published to one language/channel may recover media for another
pending channel without resending the published one. If all channels are already
published or unresolved, do not spend money preparing a replacement publication.
Keep caption preparation and required credits from stage A.

## Files and transaction checks

Expected changes are limited to existing collectors, `services/media/resolver.py`,
`planning_service.py`, `generation_service.py`,
`repositories/media_asset_repository.py`,
`services/intelligence/content_generation_service.py`,
`services/orchestration/mvp_cycle.py`, `services/publisher/publisher_service.py`,
configuration and associated tests/docs. Reuse MediaAsset metadata and existing
Post/ChannelContent identity constraints. No new dependency or migration is
assumed; if the existing schema cannot enforce an invariant, present evidence and
request approval for the minimal necessary schema change before implementation.

Required tests before approval to merge:

- Two independent PostgreSQL connections contend for one material/asset: only one
  generation call occurs, including concurrent planning and RU/EN reuse.
- Failure before claim commit, after claim commit, after request dispatch, after
  upstream success and during result commit; restart must not pay again.
- Ready and unresolved attempts cannot be regenerated; stale claim results cannot
  overwrite a newer decision; ambiguous legacy plans fail closed.
- Complete negative lookup vs not-checked/error/challenge; RSS/page failure; licensed
  RSS candidate survives page outage; configured rights denial remains enforced.
- Due-time/backoff/cap enforcement, bounded batches, permanent errors, disappearing
  RSS entry, process restart and stale source-fetch responses.
- Recovery reuses the same Post/MediaAsset and is independent of new-news dedup.
- Pending publications wait, recovered publications send once, published/unknown/
  publishing/failed rows are not reset, and no caption loss or extra Writer call.
- Run SQLite regressions and real disposable PostgreSQL concurrency tests. A
  skipped PostgreSQL test does not establish atomicity. Mock all paid/Telegram APIs.
