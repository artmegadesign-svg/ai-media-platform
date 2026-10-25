from services.orchestration.mvp_cycle import run_mvp_cycle


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

    def run(self):
        self.events.append("publish")
        if self.error is not None:
            raise self.error
        return self.result


def _run(*, items=None, approved=None, content_result=None, publisher_result=None,
         content_error=None, publisher_error=None):
    events = []
    raw_items = items or [object()]
    approved_items = approved or [object()]
    news = NewsServiceStub(raw_items, events)
    intelligence = IntelligenceStub(approved_items, events)
    content = ContentStub(content_result or [{"status": "published"}], events, error=content_error)
    session = SessionStub(events)

    def agent_factory(db):
        return PublisherAgentStub(
            db, events, result=publisher_result or [], error=publisher_error
        )

    def invoke():
        return run_mvp_cycle(
            news_service=news,
            intelligence_service=intelligence,
            content_service=content,
            session_factory=lambda: session,
            publisher_agent_factory=agent_factory,
        )

    return invoke, events, intelligence, content, session


def test_cycle_runs_all_stages_in_order_without_double_news_processing():
    raw = [object(), object()]
    publications = [object()]
    invoke, events, intelligence, _, session = _run(
        items=raw, publisher_result=publications
    )

    result = invoke()

    assert events == ["collect", "intelligence", "content_media", "publish", "db_close"]
    assert intelligence.received == raw
    assert result["collected_count"] == 2
    assert result["approved_count"] == 1
    assert result["publication_results"] == publications
    assert session.closed is True


def test_publisher_starts_only_after_content_and_media_return():
    invoke, events, _, _, _ = _run()

    invoke()

    assert events.index("content_media") < events.index("publish")


def test_session_closes_when_publisher_fails():
    invoke, events, _, _, session = _run(publisher_error=RuntimeError("publish failed"))

    try:
        invoke()
    except RuntimeError as exc:
        assert str(exc) == "publish failed"
    else:
        raise AssertionError("publisher error must propagate")

    assert events[-1] == "db_close"
    assert session.closed is True


def test_content_failure_does_not_publish_or_retry_generation():
    invoke, events, _, content, session = _run(
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
    invoke, events, _, _, session = _run(
        content_result=[{
            "status": "published",
            "post_id": 1,
            "media_generation_status": "failed",
        }]
    )

    result = invoke()

    assert result["content_results"][0]["media_generation_status"] == "failed"
    assert "publish" in events
    assert session.closed is True
