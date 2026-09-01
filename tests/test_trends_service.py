from services.trends import TrendService


def test_service_scores_and_sorts_top_trends():
    items = [
        {"title": "OpenAI выпустила GPT-5", "source": "one"},
        {"title": "GPT-5 показывает новые возможности", "source": "two"},
        {"title": "Google опубликовала research", "source": "three"},
    ]
    trends = TrendService().analyze(items)
    assert trends == sorted(
        trends,
        key=lambda trend: (
            -trend.growth_score,
            -trend.mentions,
            trend.keyword.casefold(),
        ),
    )
    assert next(trend for trend in trends if trend.keyword == "GPT-5").mentions == 2
