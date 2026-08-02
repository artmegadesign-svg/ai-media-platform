"""create channel contents table

Revision ID: 581256089bf1
Revises: 6e2f8f37bb90
Create Date: 2026-07-15 13:27:12.953259
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "581256089bf1"
down_revision: Union[str, Sequence[str], None] = "6e2f8f37bb90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_contents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("platform_post_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channels.id"],
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_channel_contents_channel_id",
        "channel_contents",
        ["channel_id"],
        unique=False,
    )

    op.create_index(
        "ix_channel_contents_post_id",
        "channel_contents",
        ["post_id"],
        unique=False,
    )

    op.execute(
        "UPDATE posts SET quality_approved = false WHERE quality_approved IS NULL"
    )

    op.alter_column(
        "posts",
        "quality_approved",
        existing_type=sa.BOOLEAN(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "posts",
        "quality_approved",
        existing_type=sa.BOOLEAN(),
        nullable=True,
    )

    op.drop_index(
        "ix_channel_contents_post_id",
        table_name="channel_contents",
    )

    op.drop_index(
        "ix_channel_contents_channel_id",
        table_name="channel_contents",
    )

    op.drop_table("channel_contents")
