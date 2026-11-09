"""Deterministic topic extraction for normalized news items."""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from services.news.normalizer import classify_category
from services.trends.models import TrendSignal


_ENTITY_PATTERN = re.compile(
    r"\b(?:OpenAI|Anthropic|Google|Meta|xAI|DeepMind|Microsoft|NVIDIA|"
    r"GPT[-\s]?\d+(?:\.\d+)?|Claude(?:\s+\d+(?:\.\d+)?)?|Gemini(?:\s+\d+(?:\.\d+)?)?|"
    r"Llama(?:\s+\d+(?:\.\d+)?)?|Grok(?:\s+\d+(?:\.\d+)?)?|"
    r"ChatGPT|transformer|нейросет\w*|искусственн\w+ интеллект\w*|"
    r"machine learning|artificial intelligence|AI|ИИ)\b",
    re.IGNORECASE,
)


def _value(item: object, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(item, Mapping) and name in item:
            return item[name]
        value = getattr(item, name, None)
        if value is not None:
            return value
    return default


def _display_keyword(keyword: str) -> str:
    canonical = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "google": "Google",
        "meta": "Meta",
        "xai": "xAI",
        "chatgpt": "ChatGPT",
        "nvidia": "NVIDIA",
    }
    compact = re.sub(r"\s+", " ", keyword).strip()
    if re.fullmatch(r"gpt[ -]?\d+(?:\.\d+)?", compact, re.I):
        return re.sub(r"\s", "-", compact).upper()
    return canonical.get(compact.casefold(), compact)


def extract_keywords(text: str) -> set[str]:
    """Use the same topic evidence for trends and editorial relevance."""
    return {_display_keyword(match.group()) for match in _ENTITY_PATTERN.finditer(text)}


class TrendAnalyzer:
    """Aggregate named AI entities and technologies across news items."""

    def analyze(self, news_items: Iterable[object]) -> list[TrendSignal]:
        topics: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "mentions": 0, "sources": set(), "categories": [],
                "news_ids": [], "dates": [],
            }
        )
        for index, item in enumerate(news_items):
            title = str(_value(item, "title", default="") or "")
            body = str(
                _value(item, "content", "description", "summary", default="") or ""
            )
            text = f"{title} {body}"
            category = classify_category(text, _value(item, "category"))
            source = str(_value(item, "source", "source_name", "url", default=index))
            news_id = _value(item, "news_id", "id")
            published = _value(item, "published_at")
            if isinstance(published, datetime):
                published = (
                    published.replace(tzinfo=timezone.utc)
                    if published.tzinfo is None else published.astimezone(timezone.utc)
                )
            # One article is one mention, even if its title repeats the entity.
            for keyword in sorted(extract_keywords(text)):
                record = topics[keyword.casefold()]
                if news_id is not None:
                    if news_id in record["news_ids"]:
                        continue
                    record["news_ids"].append(news_id)
                record["keyword"] = keyword
                record["mentions"] += 1
                record["sources"].add(source)
                record["categories"].append(category)
                if isinstance(published, datetime):
                    record["dates"].append(published)

        priority = {"model_release": 3, "research": 2, "general": 1, "opinion": 0}
        return [
            TrendSignal(
                keyword=record["keyword"],
                mentions=record["mentions"],
                source_count=len(record["sources"]),
                category=max(
                    record["categories"], key=lambda value: priority.get(value, 1)
                ),
                news_ids=record["news_ids"],
                latest_published_at=max(record["dates"], default=None),
            )
            for record in topics.values()
        ]
