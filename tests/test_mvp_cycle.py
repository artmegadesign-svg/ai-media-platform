from services.orchestration.mvp_cycle import run_mvp_cycle
from services.news.models import NewsItem


def _news(index=0):
    return NewsItem(source="test", title=f"Story {index}", url=f"https://example.com/{index}")


class Collector:
    def __init__(self, items, events):
        self.items = items
        self.events = events

    def collect(self):
        self.events.append("collect")
        return list(self.items)


class NewsServiceStub:
    def __init__(self, items, events):
        self.collectors = [Collector(items, events)]

    def collect_news(self):
        raise AssertionError("collect_news would process news before Intelligence")


class IntelligenceStub:
    def __init__(self, approved, events):
        self.approved = approved
        self.events = events
        self.received = None

    def analyze(self, items):
        self.events.append("intelligence")
        self.received = list(items)
        return self.approved


class ContentStub:
    def __init__(self, result, events, *, error=None):
        self.result = result
        self.events = events
        self.error = error
        self.calls = 0

    def generate(self, approved):
        self.events.append("content_media")
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class SessionStub:
    def __init__(self, events):
        self.events = events
        self.closed = False

    def close(self):
        self.events.append("db_close")
        self.closed = True


class PublisherAgentStub:
    def __init__(self, db, events, result=None, error=None):
        self.db = db
        self.events = events
        self.result = result or []
        self.error = error
        self.post_ids = None

    def run(self):
        raise AssertionError("controlled cycle must not publish all pending content")

    def run_for_posts(self, post_ids):
        self.events.append("publish")
        self.post_ids = list(post_ids)
        if self.error is not None:
            raise self.error
        return self.result


def _run(*, items=None, approved=None, content_result=None, publisher_result=None,
         content_error=None, publisher_error=None):
    events = []
    raw_items = items or [_news()]
    approved_items = approved or [object()]
    news = NewsServiceStub(raw_items, events)
    intelligence = IntelligenceStub(approved_items, events)
    if content_result is None:
        content_result = [{"status": "published", "post_created": True, "post_id": 101}]
    content = ContentStub(content_result, events, error=content_error)
    session = SessionStub(events)
    agents = []

    def agent_factory(db):
        agent = PublisherAgentStub(
            db, events, result=publisher_result or [], error=publisher_error
        )
        agents.append(agent)
        return agent

    def invoke():
        return run_mvp_cycle(
            news_service=news,
            intelligence_service=intelligence,
            content_service=content,
            session_factory=lambda: session,
            publisher_agent_factory=agent_factory,
        )

    return invoke, events, intelligence, content, session, agents


def test_cycle_runs_all_stages_in_order_without_double_news_processing():
    raw = [_news(1), _news(2)]
    publications = [object()]
    invoke, events, intelligence, _, session, agents = _run(
        items=raw, publisher_result=publications
    )

    result = invoke()

    assert events == ["collect", "intelligence", "content_media", "publish", "db_close"]
    assert intelligence.received == raw
    assert result["collected_count"] == 2
    assert result["approved_count"] == 1
    assert result["post_ids"] == [101]
    assert result["publication_results"] == publications
    assert agents[0].post_ids == [101]
    assert session.closed is True


def test_publisher_starts_only_after_content_and_media_return():
    invoke, events, _, _, _, _ = _run()

    invoke()

    assert events.index("content_media") < events.index("publish")


def test_session_closes_when_publisher_fails():
    invoke, events, _, _, session, _ = _run(
        publisher_error=RuntimeError("publish failed")
    )

    try:
        invoke()
    except RuntimeError as exc:
        assert str(exc) == "publish failed"
    else:
        raise AssertionError("publisher error must propagate")

    assert events[-1] == "db_close"
    assert session.closed is True


def test_content_failure_does_not_publish_or_retry_generation():
    invoke, events, _, content, session, _ = _run(
        content_error=RuntimeError("content failed")
    )

    try:
        invoke()
    except RuntimeError as exc:
        assert str(exc) == "content failed"
    else:
        raise AssertionError("content error must propagate")

    assert content.calls == 1
    assert "publish" not in events
    assert session.closed is False


def test_media_failure_result_can_continue_to_existing_publisher_behavior():
    invoke, events, _, _, session, agents = _run(
        content_result=[{
            "status": "published",
            "post_created": True,
            "post_id": 1,
            "media_generation_status": "failed",
        }]
    )

    result = invoke()

    assert result["content_results"][0]["media_generation_status"] == "failed"
    assert agents[0].post_ids == [1]
    assert "publish" in events
    assert session.closed is True


def test_cycle_publishes_only_post_ids_created_by_current_content_run():
    invoke, _, _, _, _, agents = _run(
        content_result=[
            {"status": "published", "post_created": True, "post_id": 201},
            {"status": "rejected", "post_id": None},
            {"status": "published", "post_created": True, "post_id": 202},
        ]
    )

    result = invoke()

    assert result["post_ids"] == [201, 202]
    assert agents[0].post_ids == [201, 202]


def test_cycle_with_no_created_posts_does_not_open_session_or_publish():
    invoke, events, _, _, session, agents = _run(
        content_result=[{"status": "rejected", "post_id": None}]
    )

    result = invoke()

    assert result["post_ids"] == []
    assert result["publication_results"] == []
    assert "publish" not in events
    assert agents == []
    assert session.closed is False


def test_duplicate_or_missing_creation_flag_cannot_publish_old_post():
    invoke, events, _, _, _, agents = _run(content_result=[
        {"status": "duplicate", "post_created": False, "post_id": 1},
        {"status": "published", "post_id": 2},
    ])
    assert invoke()["post_ids"] == []
    assert "publish" not in events
    assert agents == []


def test_duplicate_source_within_same_collection_is_analyzed_once(monkeypatch):
    """One duplicated URL in a batch must not trigger two paid generation paths."""
    from services.ai_engine.services.post_service import PostService

    monkeypatch.setattr(PostService, "get_existing_source_keys", lambda self, keys: set())
    item = _news(77)
    invoke, _, intelligence, _, _, _ = _run(
        items=[item, item], content_result=[{"post_created": False, "post_id": None}]
    )

    result = invoke()

    assert result["collected_count"] == 2
    assert intelligence.received == [item]
    assert result["post_ids"] == []


def test_existing_source_skips_intelligence_and_generation(monkeypatch):
    """A persisted source must not incur a new AI call after a restart."""
    from services.ai_engine.services.post_service import PostService
    from services.news.normalizer import source_identity

    item = _news(88)
    key = source_identity(item.url)[1]
    monkeypatch.setattr(PostService, "get_existing_source_keys", lambda self, keys: {key})
    invoke, events, intelligence, content, _, _ = _run(items=[item])

    result = invoke()

    assert result["collected_count"] == 1
    assert result["approved_count"] == 0
    assert "intelligence" not in events
    assert content.calls == 0
    assert result["publication_results"] == []


def test_concurrent_cycles_can_both_enter_ai_before_post_is_persisted(monkeypatch):
    """Characterize the remaining cross-cycle AI spend risk; no real AI or DB I/O."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock

    from services.ai_engine.services.post_service import PostService

    monkeypatch.setattr(PostService, "get_existing_source_keys", lambda self, keys: set())
    barrier = Barrier(2)
    lock = Lock()
    calls = []

    class ConcurrentContent:
        def generate(self, approved):
            with lock:
                calls.append(len(approved))
            barrier.wait(timeout=10)
            return [{"post_created": False, "post_id": None}]

    def cycle(_):
        events = []
        return run_mvp_cycle(
            news_service=NewsServiceStub([_news(99)], events),
            intelligence_service=IntelligenceStub([object()], events),
            content_service=ConcurrentContent(),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(cycle, range(2)))

    assert calls == [1, 1]
    assert all(result["post_ids"] == [] for result in results)


def test_generation_failure_is_not_cached_between_cycle_invocations(monkeypatch):
    """Characterize repeated AI cost risk if generation fails before persistence."""
    from services.ai_engine.services.post_service import PostService

    monkeypatch.setattr(PostService, "get_existing_source_keys", lambda self, keys: set())
    invoke, _, _, content, _, _ = _run(
        content_error=RuntimeError("simulated failure after external AI work")
    )

    for _ in range(2):
        try:
            invoke()
        except RuntimeError as exc:
            assert "simulated failure" in str(exc)
        else:
            raise AssertionError("generation failure should propagate")

    assert content.calls == 2
