"""remove_death_saves_from_npcs

Revision ID: 3de071bbd7a3
Revises: a3f226096bb3
Create Date: 2026-05-04 22:20:32.969310

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3de071bbd7a3'
down_revision: Union[str, Sequence[str], None] = 'a3f226096bb3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('npcs', 'death_save_successes')
    op.drop_column('npcs', 'death_save_failures')


def downgrade() -> None:
    op.add_column('npcs', sa.Column('death_save_failures', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('npcs', sa.Column('death_save_successes', sa.Integer(), nullable=False, server_default='0'))
