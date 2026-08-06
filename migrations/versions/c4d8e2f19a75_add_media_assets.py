"""add media assets

Revision ID: c4d8e2f19a75
Revises: a7c91e4d2f10
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4d8e2f19a75"
down_revision: Union[str, Sequence[str], None] = "a7c91e4d2f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("origin", sa.String(length=100), nullable=False),
        sa.Column("license_type", sa.String(length=50), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "source IN ('generated', 'official', 'uploaded')",
            name="ck_media_assets_source",
        ),
        sa.CheckConstraint(
            "type IN ('image', 'video', 'infographic', 'document')",
            name="ck_media_assets_type",
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_assets_post_id", "media_assets", ["post_id"])
    op.create_index("ix_media_assets_source", "media_assets", ["source"])
    op.create_index("ix_media_assets_type", "media_assets", ["type"])


def downgrade() -> None:
    op.drop_index("ix_media_assets_type", table_name="media_assets")
    op.drop_index("ix_media_assets_source", table_name="media_assets")
    op.drop_index("ix_media_assets_post_id", table_name="media_assets")
    op.drop_table("media_assets")
