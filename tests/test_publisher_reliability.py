import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Lock

import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import test_quality_issues_persistence as quality_fixtures
from core.settings import settings
from models.channel import Channel
from models.channel_content import ChannelContent
from models.metric import Metric
from models.post import Post
from services.analytics_service import AnalyticsService
from services.publisher.adapters.telegram import TelegramPublisher
from services.publisher.models import PublicationReference, PublishResult
from services.publisher.publisher_service import PublicationPersistenceError, PublisherService

quality_sessions = quality_fixtures.quality_sessions


@pytest.fixture
def sessions(quality_sessions, monkeypatch):
    monkeypatch.setattr(settings, "ai_gateway_internal_token", "test-only")
    with quality_sessions() as db:
        for row in db.query(Channel):
            row.gateway_channel_id = f"audit-{row.id}"
        db.commit()
    return quality_sessions


def seed(sessions, count=2):
    with sessions() as db:
        post = Post(title="Audit", topic="Audit", ru_content="RU", en_content="EN")
        db.add(post)
        db.flush()
        channels = db.query(Channel).order_by(Channel.id).all()
        for channel in channels[:count]:
            db.add(ChannelContent(post_id=post.id, channel_id=channel.id, status="pending"))
        db.commit()
        return post.id


def states(sessions):
    with sessions() as db:
        return [(row.status, row.platform_post_id) for row in db.query(ChannelContent).order_by(ChannelContent.id)]


def events(sessions):
    with sessions() as db:
        return [row.event_type for row in db.query(Metric).order_by(Metric.id)]


class Publisher:
    def __init__(self, send):
        self.send = send

    def publish(self, reference):
        assert isinstance(reference, PublicationReference)
        return self.send(reference)


class Factory:
    def __init__(self, send):
        self.send = send

    def create(self, db, content):
        return Publisher(self.send)


def success(reference):
    return PublishResult(success=True, platform_post_id=str(100 + reference.id))


def service(sessions, send=success, **kwargs):
    return PublisherService(session_factory=sessions, factory=Factory(send), **kwargs)


def test_each_result_commits_before_next_claim_without_live_sessions(sessions):
    seed(sessions)
    engine = sessions.kw["bind"]
    live = set()

    class TrackingSession(Session):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            live.add(id(self))

        def close(self):
            super().close()
            live.remove(id(self))

    tracked = sessionmaker(bind=engine, class_=TrackingSession, autoflush=False)

    def send(reference):
        assert not live
        assert engine.pool.checkedout() == 0
        expected = [("publishing", None), ("pending", None)] if reference.id == 1 else [
            ("published", "101"), ("publishing", None),
        ]
        assert states(sessions) == expected
        return success(reference)

    results = service(tracked, send).publish_pending()
    assert all(result.success for result in results)
    assert states(sessions) == [("published", "101"), ("published", "102")]
    assert events(sessions).count("publication_succeeded") == 2
    assert not live


def test_concurrent_claim_and_no_repeat_of_any_nonpending_state(sessions):
    seed(sessions, 1)
    barrier, lock, sent = Barrier(2), Lock(), []

    def send(reference):
        with lock:
            sent.append(reference.id)
        return success(reference)

    def worker(_):
        barrier.wait(timeout=10)
        return service(sessions, send).publish(PublicationReference(1, 1, 1))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    assert sorted(result.success for result in results) == [False, True]
    assert sent == [1]
    for status in ("published", "failed", "unknown", "publishing"):
        with sessions() as db:
            db.get(ChannelContent, 1).status = status
            db.commit()
        assert service(sessions, send).publish_pending() == []
        assert service(sessions, send).publish(PublicationReference(1, 1, 1)).error_code == "not_pending"
    assert sent == [1]


@pytest.mark.parametrize("crash_on", [1, 2])
def test_crash_leaves_only_current_claim_unresolved(sessions, crash_on):
    seed(sessions)
    sent = []

    def send(reference):
        if reference.id == crash_on:
            raise SystemExit("simulated process exit before HTTP")
        sent.append(reference.id)
        return success(reference)

    with pytest.raises(SystemExit):
        service(sessions, send).publish_pending()
    assert states(sessions) == (
        [("publishing", None), ("pending", None)] if crash_on == 1 else
        [("published", "101"), ("publishing", None)]
    )
    assert sent == ([] if crash_on == 1 else [1])
    assert events(sessions).count("publication_succeeded") == crash_on - 1


@pytest.mark.parametrize("lost_ack", [False, True])
def test_result_db_retry_never_repeats_http(sessions, monkeypatch, lost_ack):
    seed(sessions, 1)
    sent = []
    publisher = service(sessions, lambda ref: (sent.append(ref.id), success(ref))[1])
    original = publisher._write_result
    attempts = []

    def fail_once(claim, result):
        attempts.append(claim.token)
        if len(attempts) == 1:
            if lost_ack:
                assert original(claim, result)
            raise OperationalError("mock commit acknowledgement failure", {}, Exception("test only"))
        return original(claim, result)

    monkeypatch.setattr(publisher, "_write_result", fail_once)
    assert publisher.publish_pending()[0].success
    assert len(set(attempts)) == 1 and len(attempts) == 2
    assert sent == [1]
    assert states(sessions) == [("published", "101")]
    assert events(sessions).count("publication_succeeded") == 1


def test_actual_result_commit_failure_rolls_back_metric_and_status(sessions):
    seed(sessions)
    sent = []

    class FaultSession(Session):
        pass

    factory = sessionmaker(bind=sessions.kw["bind"], class_=FaultSession, autoflush=False)

    def mark_result(execute_state):
        statement = execute_state.statement
        if execute_state.is_update and any(column.key == "platform_post_id" for column in statement._values):
            execute_state.session.info["result_write"] = True

    def fail_commit(db):
        if db.info.get("result_write") and not db.in_nested_transaction():
            raise OperationalError("mock result commit failure", {}, Exception("test only"))

    event.listen(FaultSession, "do_orm_execute", mark_result)
    event.listen(FaultSession, "before_commit", fail_commit)
    try:
        with pytest.raises(PublicationPersistenceError) as error:
            service(factory, lambda ref: (sent.append(ref.id), success(ref))[1]).publish_pending()
    finally:
        event.remove(FaultSession, "do_orm_execute", mark_result)
        event.remove(FaultSession, "before_commit", fail_commit)
    assert error.value.result.platform_post_id == "101"
    assert sent == [1]
    assert states(sessions) == [("publishing", None), ("pending", None)]
    assert events(sessions) == ["publication_attempted"]


def test_stale_worker_cannot_overwrite_manual_resolution(sessions):
    seed(sessions, 1)
    publisher = service(sessions)
    claim = publisher._claim(1)
    publisher.reconcile(1, expected_status="publishing", expected_claim_token=claim.token,
                        outcome="unknown", operator="reviewer", reason="worker stopped, outcome unknown",
                        confirm_no_inflight=True)
    result = publisher._finish(claim, success(claim.reference))
    assert result.error_code == "stale_claim"
    assert states(sessions) == [("unknown", None)]
    assert "publication_succeeded" not in events(sessions)


@pytest.mark.parametrize('unknown', [False, True])
def test_analytics_failure_is_atomic_and_claim_failure_sends_nothing(sessions, unknown):
    seed(sessions)
    sent = []

    class BrokenAttempt(AnalyticsService):
        def publication_attempted(self, *args, **kwargs):
            raise RuntimeError("test attempted metric failure")

    with pytest.raises(RuntimeError):
        service(sessions, lambda ref: sent.append(ref.id), analytics_factory=BrokenAttempt).publish_pending()
    assert states(sessions) == [("pending", None)] * 2
    assert events(sessions) == [] and sent == []

    class BrokenResult(AnalyticsService):
        def publication_succeeded(self, *args, **kwargs):
            raise RuntimeError("test result metric failure")

        def publication_unknown(self, *args, **kwargs):
            raise RuntimeError("test unknown metric failure")

    with pytest.raises(PublicationPersistenceError):
        service(sessions, lambda ref: (sent.append(ref.id),
                PublishResult(success=False, outcome='unknown') if unknown else success(ref))[1],
                analytics_factory=BrokenResult).publish_pending()
    assert states(sessions) == [("publishing", None), ("pending", None)]
    assert events(sessions) == ["publication_attempted"] and sent == [1]


def test_unknown_reconciles_atomically_without_dispatch_or_false_failure(sessions):
    seed(sessions, 1)
    unknown = PublishResult(success=False, outcome="unknown", error="timeout", error_code="timeout")
    publisher = service(sessions, lambda _: unknown)
    assert publisher.publish_pending()[0].outcome == "unknown"
    row = publisher.inspect(1)
    assert events(sessions) == ["publication_attempted", "publication_unknown"]
    with pytest.raises(ValueError):
        publisher.reconcile(1, expected_status="unknown", expected_claim_token=row["claim_token"],
                            outcome="published", operator="reviewer", reason="verified", message_id=777)
    resolved = publisher.reconcile(
        1, expected_status="unknown", expected_claim_token=row["claim_token"], outcome="published",
        operator="reviewer", reason="verified channel / message 777; token=test-secret",
        message_id=777, confirm_no_inflight=True,
    )
    assert resolved["status"] == "published" and resolved["claim_token"] is None
    assert publisher.publish_pending() == []
    assert events(sessions) == ["publication_attempted", "publication_unknown", "publication_succeeded", "publication_reconciled"]
    with sessions() as db:
        assert "test-secret" not in json.dumps(db.query(Metric).order_by(Metric.id.desc()).first().metadata_)
    with pytest.raises(ValueError):
        publisher.reconcile(1, expected_status="unknown", expected_claim_token=row["claim_token"],
                            outcome="failed", operator="reviewer", reason="stale request", confirm_no_inflight=True)


def test_conflicting_analytics_outcome_aborts_reconciliation(sessions):
    seed(sessions, 1)
    publisher = service(sessions)
    claim = publisher._claim(1)
    with sessions() as db:
        AnalyticsService(db).publication_failed(1, post_id=1, channel_id=1)
    with pytest.raises(ValueError, match="different outcome"):
        publisher.reconcile(1, expected_status="publishing", expected_claim_token=claim.token,
                            outcome="published", operator="reviewer", reason="verified", message_id=7,
                            confirm_no_inflight=True)
    assert states(sessions) == [("publishing", None)]
    assert "publication_reconciled" not in events(sessions)


def test_caller_uncommitted_work_is_never_committed_or_discarded(sessions):
    seed(sessions, 1)
    with sessions() as db:
        row = db.get(ChannelContent, 1)
        row.error_message = "caller owns this change"
        with pytest.raises(ValueError, match="uncommitted"):
            PublisherService(db).publish(row)
        assert row in db.dirty
        db.rollback()
    assert states(sessions) == [("pending", None)]


def test_cli_inspects_and_resolves_one_id_without_http(sessions):
    seed(sessions)
    publisher = service(sessions)
    claim = publisher._claim(1)
    engine = sessions.kw["bind"]
    url = engine.url
    if url.get_backend_name() == "postgresql":
        with engine.connect() as db:
            schema = db.execute(text("select current_schema()")).scalar()
        url = url.set(query={"host": os.environ["AMP_QUALITY_TEST_POSTGRES_SOCKET_DIR"],
                             "options": f"-csearch_path={schema}"})
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(AMP_RECONCILE_DATABASE_URL=url.render_as_string(hide_password=False),
               AI_GATEWAY_URL="https://gateway.example", POSTGRES_DB="test", POSTGRES_USER="test",
               POSTGRES_PASSWORD="test-only", PYTHONDONTWRITEBYTECODE="1")
    code = '''import sys,runpy,socket,dotenv
from unittest.mock import patch
dotenv.load_dotenv=lambda *a,**k:False
dotenv.dotenv_values=lambda *a,**k:{}
def forbidden(*a,**k): raise AssertionError("CLI must never send HTTP")
socket.socket.connect=forbidden
sys.argv=['scripts/reconcile_publication.py',*sys.argv[1:]]
with patch('httpx.post',forbidden), patch('httpx.Client.post',forbidden):
 runpy.run_path('scripts/reconcile_publication.py',run_name='__main__')
'''
    def run(*args):
        return subprocess.run([sys.executable, "-B", "-c", code, *args], env=env, text=True, capture_output=True)
    view = run("1")
    assert view.returncode == 0, view.stderr
    assert json.loads(view.stdout)["status"] == "publishing"
    denied = run("1", "--resolve", "published")
    assert denied.returncode != 0
    resolved = run("1", "--resolve", "published", "--expected-status", "publishing",
                   "--expected-claim-token", claim.token, "--operator", "reviewer", "--reason",
                   "verified correct channel and message", "--message-id", "987", "--confirm-no-inflight")
    assert resolved.returncode == 0, resolved.stderr
    assert states(sessions) == [("published", "987"), ("pending", None)]
    assert run("1", "--resolve", "pending").returncode != 0


@pytest.mark.parametrize("exception,outcome", [
    (httpx.ConnectError("mock"), "failed"), (httpx.ConnectTimeout("mock"), "failed"),
    (httpx.PoolTimeout("mock"), "failed"), (httpx.ReadTimeout("mock"), "unknown"),
    (httpx.WriteTimeout("mock"), "unknown"), (httpx.ReadError("mock"), "unknown"),
    (httpx.WriteError("mock"), "unknown"), (httpx.RemoteProtocolError("mock"), "unknown"),
])
def test_transport_outcomes(exception, outcome):
    def handler(_):
        raise exception
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = TelegramPublisher("https://gateway.example", "test-only", "audit", "Text", client=client).publish(
            PublicationReference(1, 1, 1))
    assert not result.success and result.outcome == outcome


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 408, 409, 422, 429, 500, 502, 503, 504])
def test_http_outcomes_and_retry_after(status):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        status, json={"detail": "mock"}, headers={"Retry-After": "17"},
    ))) as client:
        result = TelegramPublisher("https://gateway.example", "test-only", "audit", "Text", client=client).publish(
            PublicationReference(1, 1, 1))
    assert result.outcome == ("failed" if status in {401, 403, 404, 422, 429} else "unknown")
    assert result.gateway_http_status == status
    assert result.retry_after_at > datetime.now(timezone.utc)


@pytest.mark.parametrize("value", [None, "", "invalid", "-1", "9999999999999999999999999999"])
def test_invalid_retry_after_is_not_a_retry(value):
    assert TelegramPublisher._retry_after(value) is None


def test_retry_after_http_date():
    assert TelegramPublisher._retry_after("Tue, 01 Jan 2030 00:00:00 GMT") == datetime(2030, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("changes", [
    {"status": "failed"}, {"provider": "other"}, {"channel_id": "wrong"},
    {"external_message_id": True}, {"external_message_id": 0}, {"external_message_id": -1},
    {"external_message_id": "123"}, {"external_message_id": 1.2}, {"external_message_id": {}},
])
def test_invalid_gateway_success_is_unknown(changes):
    body = {"status": "published", "provider": "telegram", "channel_id": "audit", "external_message_id": 123}
    body.update(changes)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        result = TelegramPublisher("https://gateway.example", "test-only", "audit", "Text", client=client).publish(
            PublicationReference(1, 1, 1))
    assert result.outcome == "unknown" and result.platform_post_id is None


@pytest.mark.parametrize("body", [None, [], {}, {"external_message_id": 1}])
def test_incomplete_gateway_response_is_unknown(body):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        result = TelegramPublisher("https://gateway.example", "test-only", "audit", "Text", client=client).publish(
            PublicationReference(1, 1, 1))
    assert result.outcome == "unknown"


@pytest.mark.parametrize('status,outcome', [(503, 'unknown'), (429, 'failed'), (200, 'published')])
def test_real_factory_http_has_no_session_and_persists_diagnostics(sessions, status, outcome):
    from services.publisher.factory import PublisherFactory

    seed(sessions, 1)
    engine = sessions.kw['bind']
    requests = []

    def handler(request):
        assert engine.pool.checkedout() == 0
        requests.append(request)
        body = {'status': 'published', 'provider': 'telegram', 'channel_id': 'audit-1',
                'external_message_id': 123} if status == 200 else {'detail': 'mock'}
        return httpx.Response(status, json=body, headers={'Retry-After': '30'})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        class Adapter(TelegramPublisher):
            def __init__(self, **kwargs):
                super().__init__(**kwargs, client=client)

        factory = PublisherFactory()
        factory.telegram_publisher_class = Adapter
        publisher = PublisherService(session_factory=sessions, factory=factory)
        assert publisher.publish_pending()[0].outcome == outcome
        assert publisher.publish_pending() == []
    row = publisher.inspect(1)
    assert row['status'] == outcome and row['gateway_http_status'] == status
    assert len(requests) == 1
    if status != 200:
        assert row['retry_after_at'] is not None and row['error_code'] is not None
    assert events(sessions) == (['publication_attempted', 'publication_unknown'] if outcome == 'unknown' else [
        'publication_attempted', 'publication_succeeded' if outcome == 'published' else 'publication_failed',
    ])


def test_preparation_error_never_sends_and_does_not_block_next_job(sessions):
    seed(sessions)
    sent = []

    class FailingFirst(Factory):
        def create(self, db, content):
            if content.id == 1:
                raise ValueError('bad local configuration; token=test-secret')
            return super().create(db, content)

    publisher = PublisherService(session_factory=sessions,
                                 factory=FailingFirst(lambda ref: (sent.append(ref.id), success(ref))[1]))
    results = publisher.publish_pending()
    assert [result.outcome for result in results] == ['failed', 'published']
    assert sent == [2]
    assert 'test-secret' not in publisher.inspect(1)['error_message']


def test_legacy_claim_requires_exact_null_match_and_can_resolve_failed(sessions):
    seed(sessions, 1)
    with sessions() as db:
        db.get(ChannelContent, 1).status = 'publishing'
        db.commit()
    publisher = service(sessions, lambda _: pytest.fail('Reconciliation must not dispatch'))
    with pytest.raises(ValueError, match='changed'):
        publisher.reconcile(1, expected_status='publishing', expected_claim_token='wrong', outcome='failed',
                            operator='reviewer', reason='confirmed not dispatched', confirm_no_inflight=True)
    result = publisher.reconcile(1, expected_status='publishing', expected_claim_token=None, outcome='failed',
                                 operator='reviewer', reason='confirmed not dispatched', confirm_no_inflight=True)
    assert result['status'] == 'failed'
    assert publisher.publish_pending() == []


def test_analytics_transactional_mode_respects_outer_rollback(sessions):
    seed(sessions, 1)
    with sessions() as db:
        with pytest.raises(RuntimeError):
            with db.begin():
                AnalyticsService(db, commit=False).publication_attempted(1, post_id=1, channel_id=1)
                raise RuntimeError('caller rollback')
    assert states(sessions) == [('pending', None)] and events(sessions) == []


def test_flushed_caller_write_is_not_silently_rolled_back(sessions):
    seed(sessions, 1)
    with sessions() as db:
        row = db.get(ChannelContent, 1)
        row.error_message = 'uncommitted but flushed'
        db.flush()
        assert not db.dirty
        with pytest.raises(ValueError, match='active transaction'):
            PublisherService(db).publish(row)
        assert db.in_transaction()
        assert db.get(ChannelContent, 1).error_message == 'uncommitted but flushed'
        db.rollback()
    assert states(sessions) == [('pending', None)]


@pytest.mark.parametrize('timeout', [0, -1, float('inf'), float('nan')])
def test_gateway_timeout_configuration_must_be_finite_positive(timeout):
    from pydantic import ValidationError
    from core.settings import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, ai_gateway_url='https://gateway.example', postgres_db='test',
                 postgres_user='test', postgres_password='test-only',
                 telegram_gateway_timeout_seconds=timeout)


@pytest.mark.parametrize('body', [None, [], {'status': 'published', 'external_message_id': 123},
                                  {'detail': 'error', 'external_message_id': 123}])
def test_unrecognized_or_contradictory_rejection_is_unknown(body):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401, json=body))) as client:
        result = TelegramPublisher('https://gateway.example', 'test-only', 'audit', 'Text', client=client).publish(
            PublicationReference(1, 1, 1))
    assert result.outcome == 'unknown'


@pytest.mark.parametrize('outcome', [None, 'published'])
@pytest.mark.parametrize('platform_post_id,valid', [
    (None, False), ('', False), (' ', False), ('\t\n', False),
    ('x' * 255, True), ('x' * 256, False), ('123', True), ('mock_42', True),
    (' 123 ', True), (123, False), (True, False),
])
def test_normalize_success_requires_nonblank_bounded_string_id(platform_post_id, valid, outcome):
    # Also exercise runtime type checks when validation was bypassed by a provider.
    original = PublishResult.model_construct(
        success=True, platform_post_id=platform_post_id, outcome=outcome,
    )
    result = PublisherService._normalize_result(original)
    assert result.success is valid
    assert original.platform_post_id == platform_post_id
    assert original.outcome == outcome
    if valid:
        assert result.outcome == 'published'
        assert result.platform_post_id == platform_post_id  # Never trim/coerce an ID.
    else:
        assert result.outcome == 'unknown'
        assert result.error_code == 'publisher_invalid_result'
        assert result.platform_post_id is None


@pytest.mark.parametrize('platform_post_id,valid', [
    (None, False), ('', False), (' ', False), ('\t\n', False),
    ('x' * 255, True), ('x' * 256, False), ('123', True), ('mock_42', True), (' 123 ', True),
])
def test_provider_success_id_validation_persists_once(sessions, platform_post_id, valid):
    seed(sessions, 1)
    sent = []

    def send(reference):
        sent.append(reference.id)
        return PublishResult(success=True, platform_post_id=platform_post_id)

    publisher = service(sessions, send)
    result = publisher.publish_pending()[0]
    assert result.success is valid
    expected_status = 'published' if valid else 'unknown'
    assert states(sessions) == [(expected_status, platform_post_id if valid else None)]
    assert events(sessions) == [
        'publication_attempted', 'publication_succeeded' if valid else 'publication_unknown',
    ]
    if not valid:
        row = publisher.inspect(1)
        assert row['error_code'] == 'publisher_invalid_result'
        assert row['published_at'] is None
    assert publisher.publish_pending() == []
    assert publisher.publish(PublicationReference(1, 1, 1)).error_code == 'not_pending'
    assert sent == [1]
