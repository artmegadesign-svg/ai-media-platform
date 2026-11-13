# Telegram news formatting

## Cause and scope

Reviewed GitHub main at de7e797 (PR #26). The initial Writer prompt explicitly
required `## HOOK`, `## INSIGHT`, `## VALUE`, and `## CONCLUSION`; MockProvider
still returns those labels. Commit 077a5fc replaced that prompt with a 700–900
character plain-news contract and added ContentPipeline.prepare_text plus Quality
checks. That protects new pipeline output but does not rewrite legacy Post rows.
The existing Telegram adapter escapes Markdown literally and, at current HEAD,
rejects it via QualityAgent.surface_issues before rendering.

Writer → ContentPipeline prepares and checks RU and EN → PostService saves Post,
ContentVariant and pending ChannelContent → PublisherFactory selects Post.ru_content
or en_content and existing media → PublisherService claims ChannelContent →
TelegramPublisher submits one request through AI Gateway. ChannelContent stores
delivery state, not the publication body. The factory deliberately remains unchanged.

## Change

The adapter delegates presentation to services/publisher/telegram_formatting.py.
It removes only the four reserved editorial labels at line starts (whole labels or
colon prefixes). Other heading text survives. Supported single-line Markdown is
`**bold**`, `__bold__`, `*italic*`, `_italic_`, inline backticks, HTTP(S) links,
ATX headings and escaped delimiters. Headline remains bold. Source HTML is literal
text, escaped exactly once; it is never trusted or decoded as existing HTML.
For example source `&` becomes `&amp;`; literal source `&amp;` becomes `&amp;amp;`
to preserve the five original characters. Unsafe Markdown links and recognized
unsupported markup fail locally. This is a bounded subset, not a CommonMark engine;
multiline code fences, lists and images within Markdown are unsupported.
Assistant prose remains rejected. The Writer and its quality contract are unchanged.

Plain and HTML representations come from the same tokens. Plain fallback preserves
link destinations as `label (URL)`. Its length accounting is conservative for links:
link URLs count even when HTML would hide them. Nesting is bounded.

The existing 4096 text / 1024 caption budgets still check both serialized Gateway
text length and Telegram visible UTF-16 units, including full required credit.
The existing fallback order remains HTML → full plain text → whitespace-only
compaction → explicit local failure. There is no truncation, summarization,
additional message, image change, schema/config change or rewrite of stored Posts.
When formatting alone exceeds the budget, plain fallback loses visual emphasis.
When complete content cannot fit, manual editorial review is required before any
new authorized attempt. Do not reset failed/unknown rows automatically.

## Safe deployment (operator action only)

1. Review the PR and wait for mandatory CI: full SQLite/PostgreSQL pytest with
   zero skips, Ruff, whitespace check, and isolated Alembic upgrade.
2. Validate rendering offline on representative existing text and media credit;
   do not call generation, Telegram, or publication methods during this review.
3. Deploy the reviewed application image through the normal release procedure.
   No migration, Gateway deployment, production configuration edit, data backfill,
   or status reset is required. Keep the prior image available for rollback.
4. Observe local_preparation/publication_not_ready errors and unknown delivery
   outcomes. Reconcile unknown outcomes; do not resend them. Rollback changes
   application code only and does not undo delivered Telegram messages.

## One control publication (separate explicit authorization)

1. Select one fresh real news Post, never Post 115 or 116. Review all facts,
   the selected language, ready image/rights and required credit. Reuse prepared
   content; do not trigger paid generation. Choose exactly one Telegram channel
   and confirm exactly one pending ChannelContent for the selected Post/channel;
   if multiple pending channels exist, stop and select an appropriately scoped
   control candidate rather than modifying statuses to force scope.
2. Run TelegramPublisher.prepare_publication offline on that exact text and
   selected media. Review full rendered headline/body/credit and both budgets.
3. Operator invokes the existing Publisher entry point scoped to the selected
   Post (PublisherService.publish_pending_for_posts([new_post_id])) exactly once.
   Do not use the unscoped batch entry point. This is a plan, not an executed send.
4. Confirm a single Gateway publication, unchanged image, correct bold headline
   and body, no editorial labels/raw supported Markdown, all facts and credit,
   and ChannelContent published with platform_post_id and published_at.
   Confirm idempotency derives from the same ChannelContent ID without resending.
5. On failed or unknown outcome stop and inspect logs/result. For unknown or
   unconfirmed persistence, reconcile the Gateway/Telegram result before any
   further action. Never automatically repeat the control send.
