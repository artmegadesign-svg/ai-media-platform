"""Add publication claim ownership and delivery diagnostics.

Revision ID: f2b7d9a4c601
Revises: d8f3a1b6c902
"""

from alembic import op
import sqlalchemy as sa

revision = "f2b7d9a4c601"
down_revision = "d8f3a1b6c902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("claim_token", sa.String(36), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("gateway_http_status", sa.Integer(), nullable=True),
        sa.Column("retry_after_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("channel_contents", column)


def downgrade() -> None:
    unresolved = op.get_bind().execute(sa.text(
        "SELECT id FROM channel_contents WHERE status IN ('publishing', 'unknown') LIMIT 1"
    )).first()
    if unresolved is not None:
        raise RuntimeError("Reconcile unresolved publications before downgrade; no data was changed")
    for name in ("retry_after_at", "gateway_http_status", "error_code", "claimed_at", "claim_token"):
        op.drop_column("channel_contents", name)
