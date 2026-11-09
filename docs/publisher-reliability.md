# Publisher Reliability Phase A

Each pending ChannelContent is conditionally claimed immediately before processing.
Claim ownership and the logical `publication_attempted` metric commit together.
Factory preparation produces an immutable identity and a provider with plain request
data. Both the preparation session and its transaction close before HTTP starts.
A supplied caller session must have no active transaction or pending changes;
Publisher never commits or rolls back caller work. The HTTP endpoint ends its own
preliminary read before calling Publisher.
The result and terminal Analytics event commit in a new transaction, fenced by
`status=publishing` and `claim_token`. Other jobs are not claimed ahead of time.

`failed` means confirmed rejection or a known failure before the publication request
was transmitted. Read/write/protocol failures, 5xx, 409 and invalid success responses
are `unknown`. Neither state is automatically retried. Interrupted `publishing`
also requires manual review. A timestamp is diagnostic, not a lease or permission
to send again. Claim tokens fence database writes, not external Telegram sends.

An ambiguous result commit is checked/retried once using a fresh session and the
same claim/result. HTTP is never retried. If persistence stays unavailable, processing
stops and the row may remain `publishing`; the error includes a safe receipt for review.
`unknown` records a nonterminal `publication_unknown` event in its result transaction,
never a false failure metric. Analytics summary counts logical jobs,
not individual HTTP attempts. Reconciliation writes terminal metrics and an audit
event atomically. Historical Analytics inconsistencies are not silently repaired.

## Manual reconciliation (no send)

Use a separately authorized administrative database via `AMP_RECONCILE_DATABASE_URL`.
The command never falls back to DATABASE_URL and never sends/enqueues publications.

```sh
python scripts/reconcile_publication.py 123
python scripts/reconcile_publication.py 123 --resolve published \
  --expected-status unknown --expected-claim-token <claim-uuid> \
  --operator <operator-id> --reason '<verified channel and message evidence>' \
  --message-id 456 --confirm-no-inflight
```

First stop/confirm completion of the old AMP worker and any outstanding Gateway
request. Check the correct Telegram channel and recorded evidence. Absence of a
visible message is not proof of non-delivery. Without adequate evidence leave the
job unresolved. `legacy-none` explicitly matches historical NULL claim tokens.
There is no reset-to-pending or retry command. Published/failed rows cannot be
rewritten by this tool. A changed status/token rejects the operation.

## Configuration and remaining limits

AMP's `TELEGRAM_GATEWAY_TIMEOUT_SECONDS` defaults to 30 seconds versus Gateway's
known Telegram timeout default of 20 seconds. Verify actual Gateway/proxy settings
and queue/lock wait budgets separately; this is not an end-to-end deadline guarantee.
`Retry-After` is stored as UTC diagnostic information, never a scheduled retry.
`published_at` is acknowledgement/reconciliation time, not guaranteed Telegram time.

Gateway's cache remains process-local. This phase cannot promise exactly-once or
safe automatic retry after an uncertain send, restart or worker change. No Gateway,
broker, scheduler or MVP backlog recovery changes are included. The global
PublisherAgent.run() remains explicitly different from MVP's scoped run_for_posts().

The additive migration leaves historical data untouched. Downgrade refuses while
any row is `publishing` or `unknown`; it never resets unresolved work to pending.
