"""add publications table

Revision ID: 6d2e694d96eb
Revises: 581256089bf1
Create Date: 2026-07-17 14:27:00.234218

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6d2e694d96eb"
down_revision: Union[str, Sequence[str], None] = "581256089bf1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        op.f("ix_publications_channel_id"),
        "publications",
        ["channel_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_publications_platform"),
        "publications",
        ["platform"],
        unique=False,
    )

    op.create_index(
        op.f("ix_publications_post_id"),
        "publications",
        ["post_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index(
        op.f("ix_publications_post_id"),
        table_name="publications",
    )

    op.drop_index(
        op.f("ix_publications_platform"),
        table_name="publications",
    )

    op.drop_index(
        op.f("ix_publications_channel_id"),
        table_name="publications",
    )

    op.drop_table("publications")
