# AI Digest publication quality

The existing Writer → Translator → Quality → Post → Publisher flow is retained.
No additional AI editor, formatter service, generation call or retry is introduced.
Media planning/generation and Gateway are unchanged.

New generated RU and EN news must each have 700–900 visible characters, a headline
on the first line (up to 140 characters), and a body. Visible length counts the plain
text with whitespace runs collapsed to a single space. It excludes presentation
markup because canonical Post/ContentVariant content is plain text.

The Writer and Translator prompts request a short factual news item, without
Markdown, HTML, service sections or assistant conversation. They prohibit inventing
facts. This does not add new source retrieval or semantic fact verification.

ContentPipeline prepares both languages with one deterministic method. It normalizes
line endings/paragraph spacing and removes recognized section labels and balanced
bold wrappers. Inline facts, numbers, URLs and quotes are retained. Ambiguous markup
and assistant prose are not silently cut: Quality rejects them. Both language checks
must pass before Post persistence. The existing score/approved/issues contract is
preserved; aggregate issues are prefixed RU/EN and the aggregate score is the lower
of the two scores. Rejected output creates no Post or publication jobs.

PublisherFactory performs a final surface/payload guard for Telegram. This does not
rerun AI or rewrite stored content. The final guard also supports short clean manual
or legacy plain text; the 700–900 news policy belongs to generation Quality.

TelegramPublisher renders the first line as an escaped <b> headline and escapes the
remaining plain text. No LLM HTML is trusted. The final serialized HTML must fit the
existing Gateway contract (4096 text / 1024 image caption). Visible UTF-16 length is
also bounded conservatively. Complete content that cannot fit is rejected locally,
without HTTP or automatic resend; it is never cut mid-sentence, tag or entity.
A caption overflow does not silently drop the image or fall back to another send.
The existing media choice, request fields, parse_mode=HTML, stable idempotency key,
claim/result transactions and unknown-delivery handling are retained.

Existing published messages are not edited or republished. Previously saved raw
pending content can be blocked by the final guard and requires explicit review.
No production data conversion or migration is included.

Tests exercise mock LLM responses, outbound HTTP payloads, both languages, rejected
persistence, escaping, transport boundaries, ready fixture media, no repeated sends,
and existing deduplication/reliability behavior on isolated SQLite/PostgreSQL.
Real LLM style/translation fidelity and final human editorial acceptance still
require a separately authorized controlled review; no paid API is used in tests.
