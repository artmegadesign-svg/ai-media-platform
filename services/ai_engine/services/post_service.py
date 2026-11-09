import json
import logging

from sqlalchemy.exc import IntegrityError

from db.session import SessionLocal

from models.post import Post
from models.content_variant import ContentVariant
from models.channel import Channel
from models.channel_content import ChannelContent
from services.analytics_service import AnalyticsService
from services.news.normalizer import source_identity
from repositories.base import is_unique_conflict

logger = logging.getLogger(__name__)


def _normalize_quality_issues(issues: object) -> str | None:
    """Keep the Text/API contract independent of database driver coercion."""
    if issues is None or isinstance(issues, str):
        return issues
    if isinstance(issues, list) and all(isinstance(issue, str) for issue in issues):
        return json.dumps(issues, ensure_ascii=False) if issues else None
    raise TypeError("quality_result.issues must be None, a string, or a list of strings")


class PostService:

    def get_existing_source_keys(self, source_keys) -> set[str]:
        keys = list(dict.fromkeys(source_keys))
        if not keys:
            return set()
        with SessionLocal() as db:
            return {
                key
                for offset in range(0, len(keys), 500)
                for (key,) in db.query(Post.source_key).filter(
                    Post.source_key.in_(keys[offset:offset + 500])
                ).all()
            }

    def find_by_source_key(self, source_key: str) -> dict | None:
        with SessionLocal() as db:
            post = db.query(Post).filter_by(source_key=source_key).first()
            if post is None:
                return None
            return {"id": post.id, "source_url": post.source_url}

    @staticmethod
    def duplicate_result(existing: dict, canonical_url: str) -> dict:
        if existing["source_url"] != canonical_url:
            raise ValueError("Stored source identity does not match the canonical URL")
        return {
            "status": "duplicate", "id": None, "post_created": False,
            "existing_post_id": existing["id"],
        }

    def save(
        self,
        topic: str,
        ru: str,
        en: str,
        quality_result: dict | None = None,
        *,
        source_url: str | None = None,
    ):

        quality_issues = _normalize_quality_issues(
            quality_result.get("issues") if quality_result else None
        )
        canonical_url, source_key = (
            source_identity(source_url) if source_url is not None else (None, None)
        )
        db = SessionLocal()

        try:
            quality_score = None
            quality_approved = False

            if quality_result:
                quality_score = quality_result.get("score")
                quality_approved = quality_result.get(
                    "approved",
                    False
                )

            post = Post(
                source_url=canonical_url,
                source_key=source_key,
                title=topic[:255],
                topic=topic,
                status="published",
                ru_content=ru,
                en_content=en,
                quality_score=quality_score,
                quality_approved=quality_approved,
                quality_issues=quality_issues
            )

            variants = [
                ContentVariant(
                    post_id=post.id,
                    language_code="ru",
                    content=ru
                ),
                ContentVariant(
                    post_id=post.id,
                    language_code="en",
                    content=en
                )
            ]

            db.add(post)
            db.flush()
            for variant in variants:
                variant.post_id = post.id
            db.add_all(variants)
            channels = (
                db.query(Channel)
                .filter(Channel.is_active.is_(True), Channel.language_code.in_(["ru", "en"]))
                .order_by(Channel.id)
                .all()
            )
            db.add_all([
                ChannelContent(channel_id=channel.id, post_id=post.id, status="pending")
                for channel in channels
            ])
            db.commit()
            db.refresh(post)

            analytics = AnalyticsService()
            try:
                analytics.post_generated(post)
            except Exception:
                logger.exception("Analytics failed after post %s was committed", post.id)
            finally:
                analytics.close()


            return {
                "post_created": True,
                "id": post.id,
                "title": post.title,
                "topic": post.topic,
                "status": post.status,
                "ru_content": post.ru_content,
                "en_content": post.en_content,
                "quality_score": post.quality_score,
                "quality_approved": post.quality_approved,
                "quality_issues": post.quality_issues
            }

        except IntegrityError as exc:
            db.rollback()
            if source_key is not None and is_unique_conflict(
                exc, "ux_posts_source_key", "posts.source_key",
            ):
                existing = self.find_by_source_key(source_key)
                if existing is not None:
                    return self.duplicate_result(existing, canonical_url)
            raise
        finally:
            db.close()


    def get_latest(self, limit: int = 50, offset: int = 0):

        db = SessionLocal()

        try:
            return (
                db.query(Post)
                .order_by(Post.created_at.desc(), Post.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

        finally:
            db.close()
