"""add gateway channel id

Revision ID: 9b61e4a2c8f0
Revises: 6d2e694d96eb
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b61e4a2c8f0"
down_revision: Union[str, Sequence[str], None] = "6d2e694d96eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("gateway_channel_id", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_channels_gateway_channel_id",
        "channels",
        ["gateway_channel_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_channels_gateway_channel_id",
        "channels",
        type_="unique",
    )
    op.drop_column("channels", "gateway_channel_id")
