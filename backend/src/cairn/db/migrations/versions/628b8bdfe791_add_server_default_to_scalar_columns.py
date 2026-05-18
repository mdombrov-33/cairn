"""add server_default to scalar columns

Revision ID: 628b8bdfe791
Revises: 6ab4ffdfb20e
Create Date: 2026-05-18 03:16:32.260923

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '628b8bdfe791'
down_revision: Union[str, Sequence[str], None] = '6ab4ffdfb20e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CHARACTER_DEFAULTS: list[tuple[str, str]] = [
    ("level", "1"),
    ("xp", "0"),
    ("temp_hp", "0"),
    ("speed", "30"),
    ("death_save_successes", "0"),
    ("death_save_failures", "0"),
    ("cr", "0"),
    ("proficiency_bonus", "2"),
    ("initiative", "0"),
    ("passive_perception", "10"),
]

_NPC_DEFAULTS: list[tuple[str, str]] = [
    ("level", "1"),
    ("disposition", "neutral"),
    ("ac", "10"),
    ("max_hp", "1"),
    ("hp", "1"),
    ("temp_hp", "0"),
    ("speed", "30"),
    ("proficiency_bonus", "2"),
    ("initiative", "0"),
    ("passive_perception", "10"),
    ("cr", "0"),
    ("xp_value", "0"),
]


def upgrade() -> None:
    for col, default in _CHARACTER_DEFAULTS:
        op.alter_column("characters", col, server_default=default)
    for col, default in _NPC_DEFAULTS:
        op.alter_column("npcs", col, server_default=default)
    op.alter_column("sessions", "combat_active", server_default="false")


def downgrade() -> None:
    for col, _ in _CHARACTER_DEFAULTS:
        op.alter_column("characters", col, server_default=None)
    for col, _ in _NPC_DEFAULTS:
        op.alter_column("npcs", col, server_default=None)
    op.alter_column("sessions", "combat_active", server_default=None)
