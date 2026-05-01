"""expand character table with full 5e fields

Revision ID: 2466abe33e8e
Revises: 02e02602f1a0
Create Date: 2026-05-01 17:02:30.842288

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2466abe33e8e'
down_revision: Union[str, Sequence[str], None] = '02e02602f1a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # LangGraph checkpoint tables are managed by langgraph-checkpoint-postgres, not Alembic.
    op.add_column('characters', sa.Column('race', sa.String(), nullable=False))
    op.add_column('characters', sa.Column('subclass', sa.String(), nullable=True))
    op.add_column('characters', sa.Column('background', sa.String(), nullable=False))
    op.add_column('characters', sa.Column('alignment', sa.String(), nullable=True))
    op.add_column('characters', sa.Column('xp', sa.Integer(), nullable=False))
    op.add_column('characters', sa.Column('portrait_url', sa.String(), nullable=True))
    op.add_column('characters', sa.Column('temp_hp', sa.Integer(), nullable=False))
    op.add_column('characters', sa.Column('ac', sa.Integer(), nullable=False))
    op.add_column('characters', sa.Column('speed', sa.Integer(), nullable=False))
    op.add_column('characters', sa.Column('death_save_successes', sa.Integer(), nullable=False))
    op.add_column('characters', sa.Column('death_save_failures', sa.Integer(), nullable=False))
    op.add_column('characters', sa.Column('proficiency_bonus', sa.Integer(), nullable=False))
    op.add_column('characters', sa.Column('initiative', sa.Integer(), nullable=False))
    op.add_column('characters', sa.Column('passive_perception', sa.Integer(), nullable=False))
    op.add_column('characters', sa.Column('spellcasting_ability', sa.String(), nullable=True))
    op.add_column('characters', sa.Column('spell_slots', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('characters', sa.Column('spells_known', postgresql.JSONB(astext_type=sa.Text()), nullable=False))
    op.add_column('characters', sa.Column('saving_throw_proficiencies', postgresql.JSONB(astext_type=sa.Text()), nullable=False))
    op.add_column('characters', sa.Column('skill_proficiencies', postgresql.JSONB(astext_type=sa.Text()), nullable=False))
    op.add_column('characters', sa.Column('features', postgresql.JSONB(astext_type=sa.Text()), nullable=False))
    op.add_column('characters', sa.Column('currency', postgresql.JSONB(astext_type=sa.Text()), nullable=False))


def downgrade() -> None:
    op.drop_column('characters', 'currency')
    op.drop_column('characters', 'features')
    op.drop_column('characters', 'skill_proficiencies')
    op.drop_column('characters', 'saving_throw_proficiencies')
    op.drop_column('characters', 'spells_known')
    op.drop_column('characters', 'spell_slots')
    op.drop_column('characters', 'spellcasting_ability')
    op.drop_column('characters', 'passive_perception')
    op.drop_column('characters', 'initiative')
    op.drop_column('characters', 'proficiency_bonus')
    op.drop_column('characters', 'death_save_failures')
    op.drop_column('characters', 'death_save_successes')
    op.drop_column('characters', 'speed')
    op.drop_column('characters', 'ac')
    op.drop_column('characters', 'temp_hp')
    op.drop_column('characters', 'portrait_url')
    op.drop_column('characters', 'xp')
    op.drop_column('characters', 'alignment')
    op.drop_column('characters', 'background')
    op.drop_column('characters', 'subclass')
    op.drop_column('characters', 'race')
