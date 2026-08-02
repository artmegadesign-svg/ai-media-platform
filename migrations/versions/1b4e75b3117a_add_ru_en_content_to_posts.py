"""add ru_en_content to posts

Revision ID: 1b4e75b3117a
Revises: 66b57c7e7041
Create Date: 2026-07-06 15:56:39.040378

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b4e75b3117a'
down_revision: Union[str, Sequence[str], None] = '66b57c7e7041'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
