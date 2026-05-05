"""add_character_resources_and_concentration

Revision ID: ae736ad8dc08
Revises: 3de071bbd7a3
Create Date: 2026-05-05 16:18:23.052533

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'ae736ad8dc08'
down_revision: Union[str, Sequence[str], None] = '3de071bbd7a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('concentration', sa.String(), nullable=True))
    op.add_column('characters', sa.Column('resources', JSONB(), nullable=False, server_default='{}'))


def downgrade() -> None:
    op.drop_column('characters', 'resources')
    op.drop_column('characters', 'concentration')
