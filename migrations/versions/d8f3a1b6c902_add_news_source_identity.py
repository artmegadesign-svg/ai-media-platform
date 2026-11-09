"""Persist Phase A source identity and unique publication pairs.

Revision ID: d8f3a1b6c902
Revises: c4d8e2f19a75
"""

from alembic import op
import sqlalchemy as sa

revision = "d8f3a1b6c902"
down_revision = "c4d8e2f19a75"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This must precede ALL DDL, including on SQLite where DDL rollback differs.
    duplicate = op.get_bind().execute(sa.text(
        "SELECT post_id, channel_id FROM channel_contents "
        "GROUP BY post_id, channel_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate is not None:
        raise RuntimeError(
            "Duplicate ChannelContent pairs exist; reconcile them before migration. "
            "No records were automatically deleted."
        )
    op.add_column("posts", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("source_key", sa.String(64), nullable=True))
    op.create_index("ux_posts_source_key", "posts", ["source_key"], unique=True)
    op.create_index(
        "ux_channel_contents_post_channel", "channel_contents",
        ["post_id", "channel_id"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_channel_contents_post_channel", table_name="channel_contents")
    op.drop_index("ux_posts_source_key", table_name="posts")
    op.drop_column("posts", "source_key")
    op.drop_column("posts", "source_url")
