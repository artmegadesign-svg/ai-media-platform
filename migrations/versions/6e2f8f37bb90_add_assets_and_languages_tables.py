"""add assets and languages tables

Revision ID: 6e2f8f37bb90
Revises: daa90f9fdcf1
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6e2f8f37bb90"
down_revision: Union[str, None] = "daa90f9fdcf1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("ru_content", sa.Text(), nullable=False),
        sa.Column("en_content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_assets_id",
        "assets",
        ["id"],
        unique=False,
    )

    op.create_table(
        "languages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_languages_code",
        "languages",
        ["code"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index("ix_languages_code", table_name="languages")
    op.drop_table("languages")

    op.drop_index("ix_assets_id", table_name="assets")
    op.drop_table("assets")
