"""add analytics metrics

Revision ID: a7c91e4d2f10
Revises: 9b61e4a2c8f0
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7c91e4d2f10"
down_revision: Union[str, Sequence[str], None] = "9b61e4a2c8f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channel_contents", sa.Column("error_message", sa.Text(), nullable=True))
    op.create_table(
        "metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("publication_id", sa.Integer(), nullable=True),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("language_code", sa.String(length=10), nullable=True),
        sa.Column("numeric_value", sa.Float(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.ForeignKeyConstraint(["publication_id"], ["channel_contents.id"]),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_metrics_event_key"),
    )
    op.create_index("ix_metrics_event_type", "metrics", ["event_type"])
    op.create_index("ix_metrics_occurred_at", "metrics", ["occurred_at"])
    op.create_index("ix_metrics_event_type_occurred_at", "metrics", ["event_type", "occurred_at"])
    op.create_index("ix_metrics_post_id", "metrics", ["post_id"])
    op.create_index("ix_metrics_publication_id", "metrics", ["publication_id"])
    op.create_index("ix_metrics_channel_id", "metrics", ["channel_id"])
    op.create_index("ix_metrics_language_code", "metrics", ["language_code"])
    op.create_index("ix_metrics_language_occurred_at", "metrics", ["language_code", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_metrics_language_occurred_at", table_name="metrics")
    op.drop_index("ix_metrics_language_code", table_name="metrics")
    op.drop_index("ix_metrics_channel_id", table_name="metrics")
    op.drop_index("ix_metrics_publication_id", table_name="metrics")
    op.drop_index("ix_metrics_post_id", table_name="metrics")
    op.drop_index("ix_metrics_event_type_occurred_at", table_name="metrics")
    op.drop_index("ix_metrics_occurred_at", table_name="metrics")
    op.drop_index("ix_metrics_event_type", table_name="metrics")
    op.drop_table("metrics")
    op.drop_column("channel_contents", "error_message")
