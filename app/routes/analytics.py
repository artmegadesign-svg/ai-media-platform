from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.dependencies import get_db
from models.channel import Channel
from models.channel_content import ChannelContent
from models.metric import Metric
from models.post import Post
from services.analytics_service import (
    EVENT_POST_GENERATED,
    EVENT_PUBLICATION_ATTEMPTED,
    EVENT_PUBLICATION_FAILED,
    EVENT_PUBLICATION_SUCCEEDED,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _filters(query, date_from, date_to, language_code, channel_id):
    if date_from is not None:
        query = query.filter(Metric.occurred_at >= date_from)
    if date_to is not None:
        query = query.filter(Metric.occurred_at <= date_to)
    if language_code is not None:
        query = query.filter(Metric.language_code == language_code)
    if channel_id is not None:
        query = query.filter(Metric.channel_id == channel_id)
    return query


@router.get("/summary")
def summary(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    language_code: str | None = None,
    channel_id: int | None = None,
    db: Session = Depends(get_db),
):
    totals_query = db.query(
        func.count(case((Metric.event_type == EVENT_POST_GENERATED, 1))).label("posts"),
        func.count(case((Metric.event_type == EVENT_PUBLICATION_ATTEMPTED, 1))).label("attempts"),
        func.count(case((Metric.event_type == EVENT_PUBLICATION_SUCCEEDED, 1))).label("successes"),
        func.count(case((Metric.event_type == EVENT_PUBLICATION_FAILED, 1))).label("failures"),
    )
    totals = _filters(
        totals_query, date_from, date_to, language_code, channel_id
    ).one()

    def breakdown(column):
        query = db.query(
            column.label("key"),
            func.count(case((Metric.event_type == EVENT_PUBLICATION_ATTEMPTED, 1))).label("attempts"),
            func.count(case((Metric.event_type == EVENT_PUBLICATION_SUCCEEDED, 1))).label("successful"),
            func.count(case((Metric.event_type == EVENT_PUBLICATION_FAILED, 1))).label("failed"),
        ).filter(column.is_not(None))
        rows = _filters(query, date_from, date_to, language_code, channel_id).group_by(column).all()
        return [
            {
                "language_code" if column is Metric.language_code else "channel_id": row.key,
                "publication_attempts": row.attempts,
                "successful_publications": row.successful,
                "failed_publications": row.failed,
                "success_rate": row.successful / row.attempts if row.attempts else 0.0,
            }
            for row in rows
        ]

    return {
        "total_posts": totals.posts,
        "total_publication_attempts": totals.attempts,
        "successful_publications": totals.successes,
        "failed_publications": totals.failures,
        "success_rate": totals.successes / totals.attempts if totals.attempts else 0.0,
        "breakdown_by_language": breakdown(Metric.language_code),
        "breakdown_by_channel": breakdown(Metric.channel_id),
    }


@router.get("/publications")
def publications(
    language_code: str | None = None,
    channel_id: int | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Metric, ChannelContent, Channel, Post)
        .join(ChannelContent, Metric.publication_id == ChannelContent.id)
        .join(Channel, Metric.channel_id == Channel.id)
        .join(Post, Metric.post_id == Post.id)
        .filter(Metric.event_type.in_([EVENT_PUBLICATION_SUCCEEDED, EVENT_PUBLICATION_FAILED]))
    )
    query = _filters(query, date_from, date_to, language_code, channel_id)
    if status:
        normalized = {"published": EVENT_PUBLICATION_SUCCEEDED, "failed": EVENT_PUBLICATION_FAILED}.get(status, status)
        query = query.filter(Metric.event_type == normalized)
    rows = query.order_by(Metric.occurred_at.desc(), Metric.id.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": metric.id,
            "publication_id": content.id,
            "post_id": post.id,
            "post_title": post.title,
            "channel_id": channel.id,
            "channel_name": channel.name,
            "language_code": metric.language_code,
            "status": "published" if metric.event_type == EVENT_PUBLICATION_SUCCEEDED else "failed",
            "occurred_at": metric.occurred_at,
            "platform_post_id": content.platform_post_id,
            "error_message": content.error_message,
        }
        for metric, content, channel, post in rows
    ]
