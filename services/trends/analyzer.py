"""Deterministic topic extraction for normalized news items."""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from services.trends.models import TrendSignal


_ENTITY_PATTERN = re.compile(
    r"\b(?:OpenAI|Anthropic|Google|Meta|xAI|DeepMind|Microsoft|NVIDIA|"
    r"GPT[-\s]?\d+(?:\.\d+)?|Claude(?:\s+\d+(?:\.\d+)?)?|Gemini(?:\s+\d+(?:\.\d+)?)?|"
    r"Llama(?:\s+\d+(?:\.\d+)?)?|Grok(?:\s+\d+(?:\.\d+)?)?|"
    r"ChatGPT|transformer|нейросет\w*|искусственн\w+ интеллект\w*|"
    r"machine learning|artificial intelligence)\b",
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


def _category(text: str) -> str:
    lowered = text.casefold()
    if any(
        word in lowered for word in ("выпуст", "релиз", "представ", "launch", "release")
    ):
        return "model_release"
    if any(
        word in lowered for word in ("исследован", "research", "paper", "benchmark")
    ):
        return "research"
    if any(word in lowered for word in ("мнение", "opinion", "считает", "колонк")):
        return "opinion"
    return "general"


class TrendAnalyzer:
    """Aggregate named AI entities and technologies across news items."""

    def analyze(self, news_items: Iterable[object]) -> list[TrendSignal]:
        topics: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"mentions": 0, "sources": set(), "categories": []}
        )
        for index, item in enumerate(news_items):
            title = str(_value(item, "title", default="") or "")
            body = str(
                _value(item, "content", "description", "summary", default="") or ""
            )
            text = f"{title} {body}"
            explicit_category = _value(item, "category")
            category = str(explicit_category or _category(text))
            source = str(_value(item, "source", "source_name", "url", default=index))
            # One article is one mention, even if its title repeats the entity.
            matches = {
                _display_keyword(match.group())
                for match in _ENTITY_PATTERN.finditer(text)
            }
            for keyword in matches:
                record = topics[keyword.casefold()]
                record["keyword"] = keyword
                record["mentions"] += 1
                record["sources"].add(source)
                record["categories"].append(category)

        priority = {"model_release": 3, "research": 2, "general": 1, "opinion": 0}
        return [
            TrendSignal(
                keyword=record["keyword"],
                mentions=record["mentions"],
                source_count=len(record["sources"]),
                category=max(
                    record["categories"], key=lambda value: priority.get(value, 1)
                ),
            )
            for record in topics.values()
        ]
