from collections.abc import Iterable

from sqlalchemy.orm import Session

from services.publisher.publisher_service import PublisherService


class PublisherAgent:
    def __init__(self, db: Session):
        self.service = PublisherService(db)

    def run(self):
        return self.service.publish_pending()

    def run_for_posts(self, post_ids: Iterable[int]):
        return self.service.publish_pending_for_posts(post_ids)
