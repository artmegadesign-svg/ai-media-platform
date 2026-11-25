"""PostgreSQL-backed, fail-closed ownership for paid source generation.

Only an expired *reserved* record can be reclaimed automatically. Once a paid
request might have started, expiry must not cause a second paid attempt.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.session import SessionLocal
from models.ai_generation_reservation import AIGenerationReservation as Reservation
from models.post import Post
from services.news.normalizer import source_identity


def _now():
    return datetime.now(timezone.utc)


def database_now(db):
    if db.bind.dialect.name == "postgresql":
        return db.execute(select(func.clock_timestamp())).scalar_one()
    return _now()


def lock_reservation(db, key):
    db.execute(select(Reservation.source_key).where(
        Reservation.source_key == key
    ).with_for_update()).first()


@dataclass(frozen=True)
class GenerationClaim:
    source_key: str
    canonical_url: str
    owner_token: str
    lease_version: int


class LostGenerationLease(RuntimeError):
    """The worker no longer has database authority to persist its output."""


class GenerationReservationService:
    def __init__(self, session_factory=SessionLocal, *, lease_seconds=300):
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.session_factory = session_factory
        self.lease_seconds = lease_seconds

    def claim(self, source_url: str) -> GenerationClaim | None:
        canonical_url, key = source_identity(source_url)
        token = str(uuid4())
        with self.session_factory() as db:
            with db.begin():
                lock_reservation(db, key)
                now = database_now(db)
                if self.reconcile_existing_in_session(db, key, canonical_url):
                    return None
                self.expire_in_session(db, key, now)
                values = dict(
                    source_key=key, canonical_url=canonical_url, status="reserved",
                    owner_token=token, lease_version=1, attempt_count=1,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    generation_started_at=None, post_id=None,
                    last_error_code=None, created_at=now, updated_at=now,
                )
                dialect = db.bind.dialect.name
                if dialect == "postgresql":
                    stmt = pg_insert(Reservation).values(**values).on_conflict_do_nothing(
                        index_elements=[Reservation.source_key]
                    )
                elif dialect == "sqlite":
                    stmt = sqlite_insert(Reservation).values(**values).on_conflict_do_nothing(
                        index_elements=[Reservation.source_key]
                    )
                else:
                    raise RuntimeError("Unsupported reservation database dialect")
                inserted = db.execute(stmt).rowcount == 1
                if inserted:
                    return GenerationClaim(key, canonical_url, token, 1)
                lock_reservation(db, key)
                now = database_now(db)
                # Atomic conditional UPDATE is the serialization point for
                # reclaiming expired work that never entered paid generation.
                changed = db.execute(
                    update(Reservation)
                    .where(
                        Reservation.source_key == key,
                        Reservation.canonical_url == canonical_url,
                        Reservation.status == "reserved",
                        Reservation.generation_started_at.is_(None),
                        Reservation.lease_expires_at <= now,
                    )
                    .values(
                        owner_token=token,
                        lease_version=Reservation.lease_version + 1,
                        attempt_count=Reservation.attempt_count + 1,
                        lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                        updated_at=now,
                    )
                )
                if changed.rowcount != 1:
                    return None
                version = db.execute(
                    select(Reservation.lease_version).where(Reservation.source_key == key)
                ).scalar_one()
                return GenerationClaim(key, canonical_url, token, version)

    @staticmethod
    def reconcile_existing_in_session(db, key, canonical_url):
        post = db.execute(select(Post.id, Post.source_url).where(
            Post.source_key == key
        )).first()
        if post is None:
            return False
        if post.source_url != canonical_url:
            raise ValueError("Stored source identity does not match canonical URL")
        db.execute(update(Reservation).where(
            Reservation.source_key == key,
            Reservation.canonical_url == canonical_url,
            Reservation.status != "completed",
        ).values(status="completed", post_id=post.id, owner_token=None,
                 lease_expires_at=None, updated_at=database_now(db)))
        return True

    def reconcile_existing(self, source_url):
        canonical_url, key = source_identity(source_url)
        with self.session_factory() as db:
            with db.begin():
                return self.reconcile_existing_in_session(db, key, canonical_url)

    @staticmethod
    def expire_in_session(db, key, now):
        return db.execute(update(Reservation).where(
            Reservation.source_key == key,
            Reservation.status == "generating",
            Reservation.lease_expires_at <= now,
        ).values(status="uncertain", owner_token=None,
                 lease_expires_at=None, updated_at=now)).rowcount == 1

    def start(self, claim: GenerationClaim) -> bool:
        with self.session_factory() as db:
            with db.begin():
                lock_reservation(db, claim.source_key)
                now = database_now(db)
                if self.reconcile_existing_in_session(db, claim.source_key, claim.canonical_url):
                    return False
                return db.execute(
                    update(Reservation)
                    .where(
                        Reservation.source_key == claim.source_key,
                        Reservation.owner_token == claim.owner_token,
                        Reservation.lease_version == claim.lease_version,
                        Reservation.status == "reserved",
                        Reservation.lease_expires_at > now,
                    )
                    .values(status="generating", generation_started_at=now, updated_at=now)
                ).rowcount == 1

    def renew(self, claim: GenerationClaim) -> bool:
        with self.session_factory() as db:
            with db.begin():
                lock_reservation(db, claim.source_key)
                now = database_now(db)
                return db.execute(
                    update(Reservation)
                    .where(
                        Reservation.source_key == claim.source_key,
                        Reservation.owner_token == claim.owner_token,
                        Reservation.lease_version == claim.lease_version,
                        Reservation.status == "generating",
                        Reservation.lease_expires_at > now,
                    )
                    .values(
                        lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                        updated_at=now,
                    )
                ).rowcount == 1

    @staticmethod
    def assert_owned_for_completion(db, claim: GenerationClaim) -> Reservation:
        # PostgreSQL row lock serializes completion against lease/owner updates.
        row = db.execute(
            select(Reservation).where(
                Reservation.source_key == claim.source_key
            ).with_for_update()
        ).scalar_one_or_none()
        now = database_now(db)
        expiry = row.lease_expires_at if row is not None else None
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if (
            row is None or row.owner_token != claim.owner_token
            or row.lease_version != claim.lease_version
            or row.canonical_url != claim.canonical_url
            or row.status != "generating"
            or expiry is None or expiry <= now
        ):
            raise LostGenerationLease("Generation reservation ownership expired")
        return row

    def finish_without_post(self, claim: GenerationClaim, *, status: str) -> bool:
        if status not in {"uncertain", "rejected"}:
            raise ValueError("Only uncertain/rejected may finish without a Post")
        with self.session_factory() as db:
            with db.begin():
                lock_reservation(db, claim.source_key)
                now = database_now(db)
                return db.execute(
                    update(Reservation)
                    .where(
                        Reservation.source_key == claim.source_key,
                        Reservation.owner_token == claim.owner_token,
                        Reservation.lease_version == claim.lease_version,
                        Reservation.status == "generating",
                        (Reservation.lease_expires_at > now) if status == "rejected" else True,
                    )
                    .values(
                        status=status, owner_token=None, lease_expires_at=None,
                        updated_at=now,
                    )
                ).rowcount == 1

    def reconcile_expired_generating(self, source_key: str) -> bool:
        """Mark an expired paid attempt uncertain; never dispatch AI."""
        with self.session_factory() as db:
            with db.begin():
                lock_reservation(db, source_key)
                return self.expire_in_session(db, source_key, database_now(db))
