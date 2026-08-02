from db.session import SessionLocal

from models.post import Post
from models.content_variant import ContentVariant

from services.channel_content_service import ChannelContentService


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

            db.add(post)
            db.commit()
            db.refresh(post)


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

            db.add_all(variants)
            db.commit()


            channel_service = ChannelContentService(db)

            channel_service.create_content(
                channel_id=1,
                post_id=post.id,
                platform_post_id=None,
                status="pending"
            )


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


    def get_latest(self, limit: int = 10):

        db = SessionLocal()

        try:
            return (
                db.query(Post)
                .order_by(Post.id.desc())
                .limit(limit)
                .all()
            )

        finally:
            db.close()
