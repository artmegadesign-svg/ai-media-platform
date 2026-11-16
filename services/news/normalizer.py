import re
from hashlib import sha256
from datetime import timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from services.news.models import NewsItem


def source_identity(source_url: str) -> tuple[str, str]:
    """Return the canonical URL and its stable Phase A identity.

    Keep URL equivalence identical to NewsNormalizer; do not infer identity
    from a title, transient NewsItem UUID or HTTP redirects.
    """
    if not isinstance(source_url, str) or not source_url.strip():
        raise ValueError("source_url must be an absolute HTTP(S) URL")
    try:
        parts = urlsplit(source_url.strip())
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError("source_url must be an absolute HTTP(S) URL")
        if parts.username is not None or parts.password is not None:
            raise ValueError("source_url must not contain credentials")
        _ = parts.port  # Reject malformed ports before any AI or database call.
    except ValueError as exc:
        raise ValueError("Invalid source_url") from exc
    canonical = NewsNormalizer._url(source_url)
    return canonical, sha256(canonical.encode("utf-8")).hexdigest()


_MODEL_TERMS = (
    r"GPT[-\s]?\d+(?:\.\d+)?|Claude|Gemini|Llama|Grok|"
    r"(?:AI|ИИ)[-\s]+(?:language\s+)?model\w*|"
    r"(?:AI|ИИ)[-\s]+модел\w*|large language models?|LLMs?|"
    r"больш\w+ языков\w+ модел\w*"
)
_AI_CONTEXT = re.compile(
    rf"\b(?:{_MODEL_TERMS}|ChatGPT|AI|ИИ|artificial intelligence|machine learning|"
    r"нейросет\w*|искусственн\w+ интеллект\w*)\b", re.I,
)
_RELEASE_EVENT = re.compile(
    r"\b(?:launch(?:es|ed|ing)?|releas(?:e|es|ed|ing)|introduc(?:e|es|ed|ing)|"
    r"unveil(?:s|ed|ing)?|announc(?:e|es|ed|ing)|выпуст\w*|выпуска\w*|представ(?:ил\w*|ля\w*)|релиз)\b", re.I,
)
_MODEL_OBJECT = re.compile(
    rf"^\s*[:—-]?\s*(?:(?:a|an|the|its|their|our|new|latest|next-generation|"
    rf"model|нов\w*|сво\w*|модел\w*|языков\w*)\s+)*(?:{_MODEL_TERMS})\b", re.I,
)
_PASSIVE_MODEL_RELEASE = re.compile(
    rf"\b(?:{_MODEL_TERMS})\s+(?:(?:was|is|has|been|был\w*)\s+)*"
    rf"{_RELEASE_EVENT.pattern}", re.I,
)
_TOOL_OBJECT = re.compile(
    r"^\s*[:—-]?\s*(?:(?:a|an|the|its|their|our|new|latest|нов\w*|сво\w*)\s+)*"
    rf"(?:(?:{_MODEL_TERMS})(?:\s+\d+(?:\.\d+)*)?\s+)?"
    r"(?:(?:AI|ИИ)[-\s]+)?(?:coding\s+)?"
    r"(?:tools?|apps?|applications?|assistants?|SDK|API|ChatGPT|Claude Code|"
    r"инструмент\w*|приложени\w*|ассистент\w*)\b", re.I,
)
_RESEARCH_EVIDENCE = re.compile(
    r"\b(?:research|papers?|benchmarks?|исследован\w*|научн\w+ стать\w*)\b", re.I,
)
_UNCERTAIN_EVENT = re.compile(
    r"\b(?:plans?|planning|upcoming|rumou?rs?|denies|denied|delays?|not|no|will|"
    r"could|may|coming soon|scheduled|expected|ожида\w*|планир\w*|слух\w*|не|отлож\w*|опроверг\w*)\b", re.I,
)


def has_ai_context(text: str) -> bool:
    """Require AI or model/product evidence, not just an organization name."""
    return _AI_CONTEXT.search(text) is not None


_API_OBJECT = re.compile(r"\bAPIs?\b", re.I)
_TOOL_NOUN = re.compile(r"\b(?:tools?|apps?|applications?|assistants?|SDK|инструмент\w*|приложени\w*|ассистент\w*)\b", re.I)
_EDUCATION = re.compile(r"\b(?:courses?|curriculum|training program|education(?:al)?|scholarships?|курсы?|обучени\w*|образовательн\w*)\b", re.I)
_CORPORATE = re.compile(r"\b(?:customer stor(?:y|ies)|success stor(?:y|ies)|sponsor\w*|advertis\w*|campaign|annual report|корпоративн\w*|реклам\w*)\b", re.I)
_PUBLICATION = re.compile(r"\b(?:publish(?:es|ed|ing)?|releas(?:e|es|ed|ing)|публику\w*|опубликов\w*)\b", re.I)
_UPDATE = re.compile(r"\b(?:updates?|upgrades?|adds?|added|обнов\w*|добав\w*)\b", re.I)
_AVAILABILITY = re.compile(r"\b(?:available (?:now|today|to|for|through|via)|available in (?:(?:public|private|limited) )?preview|(?:now |generally )available|developers can|download|доступ\w*)\b", re.I)
_CAPABILITY = re.compile(r"\b(?:supports?|enables?|provides?|allows?|reduces?|improves?|handles?|gives?|delivers?|evaluate|поддерж\w*|позвол\w*|снижа\w*)\b", re.I)
_MEASURE = re.compile(r"\b\d[\d,.]*\s*(?:%|[- ]tokens?\b|languages?\b|milliseconds?\b|ms\b|questions?\b|язык\w*|токен\w*)", re.I)
_CONCRETE_CAPABILITY = re.compile(r"\b(?:streaming|tool calling|structured outputs|multimodal|offline|local inference|code execution|multi-step workflows)\b", re.I)
_ARTIFACT = re.compile(r"\b(?:paper|dataset|code)\s+(?:is |are )?(?:now )?available\b|arxiv\.org/|doi\.org/", re.I)


def _sentences(text: str) -> list[str]:
    # Keep model versions and artifact URLs intact; stop at sentence punctuation.
    return [part.strip() for part in re.split(r"\.(?=\s|$)|[!?;\n]+", text) if part.strip()]


# Bound raw work as well as selected evidence. Metadata cannot extend this scan.
_EVIDENCE_CHARS = 4_000
_EVIDENCE_BLOCKS = 16
_EVIDENCE_SENTENCES = 6
_DATE_BLOCK = re.compile(
    r"(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.? \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})", re.I,
)
_ROLE_BLOCK = re.compile(
    r"(?:Product Manager|Research Director|Product Director|Design & Engineering Lead|Principal Scientist|(?:Senior )?(?:Research Scientist|Software Engineer)|"
    r"(?:VP|Vice President) of (?:Product|Engineering|Research))"
    r"(?:, [\w &-]+)?", re.I,
)
_NAME_BLOCK = re.compile(r"[^\W\d_][^\W\d_'-]*(?:[ '-][^\W\d_][^\W\d_'-]*){1,3}")
_BACKGROUND = re.compile(r"\b(?:about the author|author biography|research interests|written by|previously)\b", re.I)
_OTHER_EVENT = re.compile(r"^(?:another|elsewhere|in other|related (?:news|stories))\b", re.I)
_PRODUCT_UPGRADE = re.compile(
    r"\b(?:gets?|receives?|has received)\s+(?:a\s+)?(?:major |significant |new )?upgrade\b|"
    r"\b(?:brings?|bringing|integrates?|integrating)\b.*\b(?:intelligence|AI|model)\b.*\b(?:to|into|with)\b", re.I,
)


def _uncertain(text: str) -> bool:
    # A supported yes/no question format is not a denial of a release.
    return bool(
        _UNCERTAIN_EVENT.search(re.sub(r"\byes/no\b", "binary", text, flags=re.I))
        or re.search(r"\b(?:next|coming)\s+(?:(?:few|several)\s+)?(?:weeks?|months?|years?)\b", text, re.I)
    )


def evidence_sentences(content: str) -> list[str]:
    """Read a bounded prefix; skip only full dates and adjacent name/role pairs.

    Metadata stays in NewsItem.content. Unknown prose counts against the budget;
    biographies and related-news boundaries stop selection rather than being
    skipped to reach a later, potentially unrelated announcement.
    """
    prefix = content[:_EVIDENCE_CHARS]
    raw_blocks = [block for block in prefix.splitlines() if block.strip()]
    blocks = [re.sub(r"\s+", " ", block).strip() for block in raw_blocks[:_EVIDENCE_BLOCKS]]
    cut_tail = (len(content) > _EVIDENCE_CHARS and len(raw_blocks) <= _EVIDENCE_BLOCKS
                and not prefix.endswith((".", "!", "?", "\n")))
    result = []
    index = 0
    while index < len(blocks) and len(result) < _EVIDENCE_SENTENCES:
        block = blocks[index]
        if _DATE_BLOCK.fullmatch(block):
            index += 1
            continue
        if (_NAME_BLOCK.fullmatch(block) and all(word[0].isupper() for word in block.split())
                and not has_ai_context(block) and index + 1 < len(blocks)
                and _ROLE_BLOCK.fullmatch(blocks[index + 1])):
            index += 2
            continue
        sentences = _sentences(block)
        if cut_tail and index == len(blocks) - 1:
            sentences = sentences[:-1]  # Never evaluate a cut claim without its qualifier.
        for sentence in sentences:
            if _BACKGROUND.search(sentence) or _OTHER_EVENT.search(sentence):
                return result
            result.append(sentence)
            if len(result) == _EVIDENCE_SENTENCES:
                break
        index += 1
    return result


def _matches_subject(subject: set[str], text: str, title: str = "") -> bool:
    words = {word.casefold() for word in re.findall(r"\w+", text)}
    if subject and subject <= words:
        return True
    # A branded name may be shortened by dropping its first component, provided
    # the distinctive remainder and object type remain, with no rival prefix.
    ordered = list(dict.fromkeys(word.casefold() for word in re.findall(r"\w+", title.split(":", 1)[0]) if word.casefold() in subject))
    if len(ordered) < 2:
        return False
    short = ordered[1:]
    if not set(short) <= words:
        return False
    phrase = r"\s+".join(re.escape(word) for word in short)
    if _API_OBJECT.search(title):
        phrase += r"\s+API\b"
    elif _PRODUCT_UPGRADE.search(title):
        phrase += r"\b"
    else:
        return False
    for match in re.finditer(r"\b" + phrase, text, re.I):
        prefix = text[:match.start()].rstrip()
        previous = re.search(r"([\w'-]+)$", prefix)
        if not previous or previous.group().casefold() in {"the", "our", "this", "in", "to", "with", "of", "through", "via", "on", "for", "and"}:
            return True
    return False


def _event_category(sentence: str) -> str:
    if not has_ai_context(sentence):
        return "general"
    if _uncertain(sentence):
        return "rumor"
    if _EDUCATION.search(sentence):
        return "education"
    if _CORPORATE.search(sentence):
        return "corporate"
    if _PRODUCT_UPGRADE.search(sentence) or re.search(r"\b(?:new features|new capabilities|on more devices)\b", sentence, re.I):
        return "product_update"
    # Bind publication/release to its object, before background qualifications.
    event = _RELEASE_EVENT.search(sentence) or _PUBLICATION.search(sentence)
    available = re.search(r"\b(?:is|are)\s+(?:now |generally )?available\b", sentence, re.I)
    obj = ""
    if event:
        obj = sentence[event.end():]
    elif available:
        obj = sentence[:available.start()]
    obj = re.split(r"\b(?:powered by|using|through|via|for|with|about|mentioning|based on)\b", obj, maxsplit=1, flags=re.I)[0]
    if _RESEARCH_EVIDENCE.search(obj) and _PUBLICATION.search(sentence):
        return "research"
    if not event and re.match(r"(?:new |нов\w* )?(?:.*?\b)?(?:research paper|исследование)\b", sentence, re.I):
        return "research"
    if event or available:
        if _API_OBJECT.search(obj):
            return "api_release"
        if event and re.search(r",\s*(?:an?|the)\s+(?:new\s+)?AI\s+(?:solution|platform|service)\b", sentence[event.end():], re.I):
            return "tool_release"
        if _TOOL_NOUN.search(obj) or _TOOL_OBJECT.search(obj):
            return "tool_release"
        if _MODEL_OBJECT.search(obj):
            if re.search(r"\bin(?:to)?\s+(?:an? |the |its )?(?:AI )?(?:search|app|assistant|product|browser)\b", obj, re.I):
                return "product_update"
            return "model_release"
    if _PASSIVE_MODEL_RELEASE.search(sentence):
        return "model_release"
    if _UPDATE.search(sentence) and (_CAPABILITY.search(sentence) or _CONCRETE_CAPABILITY.search(sentence)
                                    or re.search(r"\b(?:updates?|upgrades?)\s+(?:its\s+)?(?:ChatGPT|Gemini|AI|ИИ)\b", sentence, re.I)):
        return "product_update"
    return "general"


def _subject_words(title: str) -> set[str]:
    generic = {"a", "an", "the", "new", "our", "its", "introducing", "update", "updates",
               "model", "ai", "news", "api", "tool",
               "launches", "releases", "introduces", "publishes", "research", "paper",
               "of", "on", "in", "at", "to", "for", "from", "with", "by", "and",
               "or", "as", "is", "are", "was", "has", "have"}
    generic |= {"gets", "get", "a", "major", "significant", "upgrade", "upgrades", "s",
                "today", "announces", "introduce", "launch", "release"}
    obj = re.split(r"\b(?:powered by|based on|through|with)\b", title.split(":", 1)[0], maxsplit=1, flags=re.I)[0]
    upgrade = re.search(r"\b(?:gets?|receives?|has received)\b", obj, re.I)
    action = _RELEASE_EVENT.search(obj) or _PUBLICATION.search(obj) or _UPDATE.search(obj)
    if upgrade:
        obj = obj[:upgrade.start()]  # The subject is the product receiving an upgrade.
    elif action:
        obj = obj[action.end():]  # Do not bind evidence to the announcing company.
    return {word.casefold() for word in re.findall(r"\w+", obj) if not word.isdecimal()} - generic


def event_category(title: str, content: str = "") -> str:
    """Prefer the headline event, then a linked lead; never scan a whole biography."""
    if re.search(r"\b(?:мнение|opinion|считает|колонк\w*)\b", title, re.I):
        return "opinion"
    headline = _event_category((_sentences(title) or [title])[0])
    lead = evidence_sentences(content)[:2]
    # An explicit educational/corporate headline outranks research in the body.
    if _EDUCATION.search(title):
        return "education"
    if _CORPORATE.search(title):
        return "corporate"
    if headline not in {"general", "rumor"} and lead:
        subject = _subject_words(title)
        if (not subject or _matches_subject(subject, lead[0], title)) and _event_category(lead[0]) == "rumor":
            return "rumor"
    if re.search(r"\b(?:roundup|retrospective|last month|last year)\b", title, re.I):
        return "general"
    if lead and re.match(r"(?:previously|originally|last month|last year)\b", lead[0], re.I):
        return "general"
    if (headline == "model_release" and lead and not re.search(r"\bmodel\b", title, re.I)
            and _matches_subject(_subject_words(title), lead[0], title)
            and re.search(r",\s*(?:an?|the)\s+AI\s+(?:solution|platform|service)\b", lead[0], re.I)):
        return "tool_release"
    if headline != "general":
        return headline
    # A title without a verb needs facts about its subject, not another release.
    subject = _subject_words(title)
    for sentence in lead:
        if re.search(r"\b(?:about the author|author biography|previously|research interests|written by)\b", sentence, re.I):
            continue
        if subject and not _matches_subject(subject, sentence, title):
            continue
        candidate = _event_category(sentence)
        if candidate != "general":
            return candidate
    return "general"


def classify_category(text: str, category: str | None = None, *, content: str = "") -> str:
    """Preserve declared specific categories; re-evaluate unspecified/general ones."""
    explicit = (category or "").strip().casefold()
    if explicit and explicit not in {"other", "general"}:
        return explicit
    return event_category(text, content)


def event_impact(title: str, content: str, category: str) -> int:
    """An explicit availability + concrete capability supports broad practical use.

    Research additionally needs a published artifact and a measured result.
    The evidence window is the lead, not unrelated background later in the page.
    """
    base = {"model_release": 80, "api_release": 60, "tool_release": 60,
            "product_update": 60, "research": 60}.get(category, 0)
    if not base or event_category(title, content) != category:
        return 0
    if category == "model_release" and re.search(r"\bannounc\w*\b", title, re.I):
        base = 60  # An announcement alone need not establish availability.
    sentences = evidence_sentences(content)
    lead = " ".join(sentences)
    # Require a repeated subject, or a generic headline whose event is in the lead.
    if not lead:
        return base
    subject = _subject_words(title)
    first = sentences[0]
    if subject:
        if not _matches_subject(subject, first, title):
            return base
    elif _event_category(first) != category:
        return base
    if _uncertain(first):
        return base
    # Availability names the existing product type; it need not repeat the
    # headline's update verb. Other event types must agree with the headline.
    if category != "product_update" and _event_category(first) not in {"general", category}:
        return base
    linked = [first]
    for sentence in sentences[1:]:
        if _uncertain(sentence):
            continue
        if re.match(r"(?:another|elsewhere|previously|in other)\b", sentence, re.I):
            break
        same = _matches_subject(subject, sentence, title)
        if _event_category(sentence) in {"api_release", "tool_release", "model_release", "product_update", "research"} and not same:
            # A concrete second object breaks coreference for subsequent "it".
            if not re.match(r"(?:it|its|the (?:API|tool|model|paper|study|update))\b", sentence, re.I):
                break
        referent = re.match(r"(?:it|its|this|evaluate|the (?:API|tool|model|paper|study|update|platform|solution|service)|developers can|initially available)\b", sentence, re.I)
        dependent = re.search(r",\s*it\s+(?:enables|supports|provides|allows)\b", sentence, re.I)
        if same or referent or dependent:
            linked.append(sentence)
    lead = " ".join(linked)
    if category == "research":
        strong = bool(_ARTIFACT.search(lead) and _MEASURE.search(lead) and _PUBLICATION.search(lead))
    else:
        modalities = {word.casefold().rstrip("s") for word in re.findall(r"\b(?:text|images?|audio|video|PDFs?)\b", lead, re.I)}
        available = any(
            _AVAILABILITY.search(sentence)
            and not re.search(r"\b(?:waitlist|waiting list|pre[- ]order|coming soon|over the next)\b", sentence, re.I)
            for sentence in linked
        )
        strong = bool(available and _CAPABILITY.search(lead)
                      and (_MEASURE.search(lead) or _CONCRETE_CAPABILITY.search(lead)
                           or len(modalities) >= 3))
    return 80 if strong else base


class NewsNormalizer:
    """Clean news records and discard URL and near-title duplicates."""

    def __init__(self, title_similarity: float = 0.85) -> None:
        self.title_similarity = title_similarity

    def normalize(self, news: list[NewsItem]) -> list[NewsItem]:
        result: list[NewsItem] = []
        urls: set[str] = set()
        titles: list[str] = []
        for original in news:
            item = original.model_copy(deep=True)
            item.source = self._clean(item.source)
            item.title = self._clean(item.title)
            item.content = "\n".join(self._clean(line) for line in (item.content or "").splitlines() if line.strip()) or None
            item.url = self._url(item.url)
            item.image_url = self._url(item.image_url) if item.image_url else None
            item.category = classify_category(
                item.title, item.category, content=item.content or ""
            )
            if item.published_at:
                if item.published_at.tzinfo is None:
                    item.published_at = item.published_at.replace(tzinfo=timezone.utc)
                else:
                    item.published_at = item.published_at.astimezone(timezone.utc)
            comparable = item.title.casefold()
            if not item.title or not item.url or item.url in urls:
                continue
            if any(SequenceMatcher(None, comparable, title).ratio() >= self.title_similarity for title in titles):
                continue
            urls.add(item.url)
            titles.append(comparable)
            result.append(item)
        return result

    @staticmethod
    def _clean(value: str | None) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    @staticmethod
    def _url(value: str) -> str:
        parts = urlsplit(value.strip())
        query = urlencode(
            [
                (key, val)
                for key, val in parse_qsl(parts.query, keep_blank_values=True)
                if not key.lower().startswith("utm_")
            ]
        )
        path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))
