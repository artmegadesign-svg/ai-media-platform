import logging

from db.session import SessionLocal

from models.post import Post
from models.content_variant import ContentVariant
from models.channel import Channel
from models.channel_content import ChannelContent
from services.analytics_service import AnalyticsService

logger = logging.getLogger(__name__)


class PostService:

    def save(
        self,
        topic: str,
        ru: str,
        en: str,
        quality_result: dict | None = None
    ):

        db = SessionLocal()

        try:
            quality_score = None
            quality_approved = False
            quality_issues = None

            if quality_result:
                quality_score = quality_result.get("score")
                quality_approved = quality_result.get(
                    "approved",
                    False
                )
                quality_issues = quality_result.get(
                    "issues"
                )

            post = Post(
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
