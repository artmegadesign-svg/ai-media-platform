"""create channels table

Revision ID: daa90f9fdcf1
Revises: f7c688c7ebcc
Create Date: 2026-07-13 13:13:49.775928
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "daa90f9fdcf1"
down_revision: Union[str, Sequence[str], None] = "f7c688c7ebcc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("language_code", sa.String(length=10), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_channels_language_code"),
        "channels",
        ["language_code"],
        unique=False,
    )

    op.create_index(
        op.f("ix_channels_name"),
        "channels",
        ["name"],
        unique=True,
    )

    op.create_index(
        op.f("ix_channels_platform"),
        "channels",
        ["platform"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_channels_platform"),
        table_name="channels",
    )

    op.drop_index(
        op.f("ix_channels_name"),
        table_name="channels",
    )

    op.drop_index(
        op.f("ix_channels_language_code"),
        table_name="channels",
    )

    op.drop_table("channels")
