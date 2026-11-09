import re
from datetime import timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from services.news.models import NewsItem


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
    r"unveil(?:s|ed|ing)?|выпуст\w*|выпуска\w*|представ(?:ил\w*|ля\w*)|релиз)\b", re.I,
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
    r"could|may|ожида\w*|планир\w*|слух\w*|не|отлож\w*|опроверг\w*)\b", re.I,
)


def has_ai_context(text: str) -> bool:
    """Require AI or model/product evidence, not just an organization name."""
    return _AI_CONTEXT.search(text) is not None


def classify_category(text: str, category: str | None = None) -> str:
    """Infer an unspecified category using the shared News/Trends policy."""
    explicit = (category or "").strip().casefold()
    if explicit and explicit != "other":
        return explicit
    if re.search(r"\b(?:мнение|opinion|считает|колонк\w*)\b", text, re.I):
        return "opinion"
    # Evidence must occur in the same sentence; a model mentioned elsewhere is
    # not evidence that the announced product is an AI model.
    # A dot between digits belongs to a version such as GPT-5.1, not a sentence.
    for sentence in re.split(r"(?<!\d)\.|\.(?!\d)|[!?;\n]+", text):
        if not has_ai_context(sentence) or _UNCERTAIN_EVENT.search(sentence):
            continue
        if _RESEARCH_EVIDENCE.search(sentence):
            return "research"
        event = _RELEASE_EVENT.search(sentence)
        if event is None:
            continue
        # A tool powered by a named model is still a tool, not a model release.
        if _TOOL_OBJECT.search(sentence[event.end():]):
            return "tool_release"
        if _MODEL_OBJECT.search(sentence[event.end():]) or _PASSIVE_MODEL_RELEASE.search(sentence):
            return "model_release"
    return "general"


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
            item.content = self._clean(item.content) or None
            item.url = self._url(item.url)
            item.image_url = self._url(item.image_url) if item.image_url else None
            item.category = classify_category(
                f"{item.title} {item.content or ''}", item.category
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
