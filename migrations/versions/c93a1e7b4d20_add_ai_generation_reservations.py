"""Add durable AI generation reservation ownership.

Revision ID: c93a1e7b4d20
Revises: f2b7d9a4c601
"""
from alembic import op
import sqlalchemy as sa

revision = "c93a1e7b4d20"
down_revision = "f2b7d9a4c601"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_generation_reservations",
        sa.Column("source_key", sa.String(64), primary_key=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("owner_token", sa.String(36), nullable=True),
        sa.Column("lease_version", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generation_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('reserved', 'generating', 'completed', 'uncertain', 'rejected')",
            name="ck_ai_generation_reservation_status",
        ),
    )


def downgrade() -> None:
    # Dropping ownership records while work is in flight can cause double billing.
    active = op.get_bind().execute(sa.text(
        "SELECT source_key FROM ai_generation_reservations "
        "WHERE status IN ('reserved', 'generating', 'uncertain') LIMIT 1"
    )).first()
    if active is not None:
        raise RuntimeError("Reconcile active/uncertain AI work before downgrade")
    op.drop_table("ai_generation_reservations")
