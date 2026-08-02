"""add quality metadata to posts

Revision ID: f7c688c7ebcc
Revises: 1b4e75b3117a
Create Date: 2026-07-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7c688c7ebcc"
down_revision: Union[str, Sequence[str], None] = "1b4e75b3117a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column(
            "quality_score",
            sa.Integer(),
            nullable=True
        )
    )

    op.add_column(
        "posts",
        sa.Column(
            "quality_approved",
            sa.Boolean(),
            nullable=True
        )
    )

    op.add_column(
        "posts",
        sa.Column(
            "quality_issues",
            sa.Text(),
            nullable=True
        )
    )

    op.add_column(
        "posts",
        sa.Column(
            "generation_source",
            sa.String(length=100),
            nullable=True
        )
    )


def downgrade() -> None:
    op.drop_column("posts", "generation_source")
    op.drop_column("posts", "quality_issues")
    op.drop_column("posts", "quality_approved")
    op.drop_column("posts", "quality_score")
