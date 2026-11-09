from datetime import datetime

import pytest

from services.news.models import NewsItem
from services.news.normalizer import NewsNormalizer, source_identity


def _news(title: str, url: str) -> NewsItem:
    return NewsItem(
        source=" OpenAI ", title=title, url=url, published_at=datetime(2026, 8, 25)
    )


def test_source_identity_reuses_canonicalization_and_ignores_transient_ids():
    first = source_identity("https://OPENAI.com/story/?utm_source=feed#section")
    assert first == source_identity("https://openai.com/story")
    assert first[0] == "https://openai.com/story"
    assert len(first[1]) == 64
    assert first == source_identity(first[0])
    assert first != source_identity("https://openai.com/other")


@pytest.mark.parametrize("url", [None, "", " ", "/relative", "ftp://example.com/a",
                                    "https://user:password@example.com/a", "https://example.com:bad/a"])
def test_invalid_source_identity_fails_closed(url):
    with pytest.raises(ValueError):
        source_identity(url)


def test_normalizer_removes_duplicate_canonical_urls():
    news = [
        _news("First", "https://OPENAI.com/news/first/?utm_source=test"),
        _news("Different", "https://openai.com/news/first"),
    ]

    result = NewsNormalizer().normalize(news)

    assert len(result) == 1
    assert result[0].url == "https://openai.com/news/first"
    assert result[0].published_at.tzinfo is not None


def test_normalizer_removes_similar_titles_and_cleans_text():
    news = [
        _news("  Announcing   our newest model ", "https://example.com/one"),
        _news("Announcing our newest model!", "https://example.com/two"),
    ]

    result = NewsNormalizer(title_similarity=0.8).normalize(news)

    assert len(result) == 1
    assert result[0].title == "Announcing our newest model"


@pytest.mark.parametrize(("title", "category", "expected"), [
    ("OpenAI releases GPT-5", "other", "model_release"),
    ("New Gemini research paper", "other", "research"),
    ("A weekend travel diary", "other", "general"),
    ("OpenAI releases GPT-5", "opinion", "opinion"),
])
def test_unspecified_category_is_inferred_without_overwriting_explicit_category(
    title, category, expected,
):
    item = _news(title, "https://example.com/story")
    item.category = category

    normalized = NewsNormalizer().normalize([item])[0]

    assert normalized.category == expected
    assert item.category == category  # Normalization must not mutate the source.


@pytest.mark.parametrize(("title", "expected"), [
    ("OpenAI releases GPT-5", "model_release"),
    ("Google launches its new AI model", "model_release"),
    ("OpenAI представила новую модель GPT-5", "model_release"),
    ("GPT-5 was released by OpenAI", "model_release"),
    ("OpenAI releases GPT-5 through its API", "model_release"),
    ("OpenAI launches an AI coding assistant", "tool_release"),
    ("OpenAI releases ChatGPT app", "tool_release"),
    ("OpenAI releases an AI tool powered by GPT-5", "tool_release"),
    ("OpenAI releases an API for GPT-5", "tool_release"),
    ("Google представила ИИ-инструмент", "tool_release"),
    ("OpenAI releases a research paper about GPT-5", "research"),
    ("Исследование возможностей ИИ", "research"),
    ("Google launches a travel report", "general"),
    ("OpenAI releases its annual financial report", "general"),
    ("A bicycle manufacturer releases a new model", "general"),
    ("Google releases a travel report mentioning GPT-5", "general"),
    ("GPT-5 is discussed as Google releases a travel report", "general"),
    ("OpenAI releases a travel report. GPT-5 is mentioned elsewhere", "general"),
    ("Google publishes a research paper about tourism", "general"),
    ("OpenAI plans to release GPT-5", "general"),
    ("OpenAI denies the release of GPT-5", "general"),
    ("Opinion on the launch of GPT-5", "opinion"),
])
def test_classification_requires_specific_ai_event_evidence(title, expected):
    result = NewsNormalizer().normalize([_news(title, "https://example.com/story")])[0]

    assert result.category == expected


@pytest.mark.parametrize("category", ["model_release", "tool_release", "research", "opinion"])
def test_explicit_content_categories_are_preserved_even_when_text_is_inconclusive(category):
    item = _news("An update from the company", "https://example.com/story")
    item.category = category

    assert NewsNormalizer().normalize([item])[0].category == category


@pytest.mark.parametrize(("title", "expected"), [
    ("OpenAI releases GPT-5.1 research paper", "research"),
    ("OpenAI releases GPT-4.5 research paper", "research"),
    ("OpenAI releases GPT-5.1", "model_release"),
    ("OpenAI releases GPT-4.5", "model_release"),
    ("OpenAI releases GPT-5 SDK", "tool_release"),
    ("OpenAI releases GPT-5 API", "tool_release"),
    ("OpenAI releases GPT-5.1 SDK", "tool_release"),
    ("Google launches Gemini SDK", "tool_release"),
    ("Google launches Gemini 2.5 SDK", "tool_release"),
    ("Anthropic releases Claude Code", "tool_release"),
    ("OpenAI releases an AI application powered by GPT-5", "tool_release"),
    ("OpenAI releases GPT-5.1 through its API", "model_release"),
    ("OpenAI releases GPT-5.1. A research paper is discussed elsewhere", "model_release"),
    ("OpenAI releases a travel report. GPT-5.1 is mentioned elsewhere", "general"),
])
def test_model_versions_and_model_named_tools_preserve_event_type(title, expected):
    normalized = NewsNormalizer().normalize([_news(title, "https://example.com/story")])[0]

    assert normalized.category == expected
