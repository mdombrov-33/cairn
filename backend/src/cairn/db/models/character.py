import uuid
from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), index=True)
    owner_id: Mapped[str] = mapped_column(index=True)

    # identity
    name: Mapped[str]
    race: Mapped[str]
    class_: Mapped[str] = mapped_column("class")
    subclass: Mapped[str | None]
    background: Mapped[str]
    alignment: Mapped[str | None]
    level: Mapped[int] = mapped_column(default=1)
    xp: Mapped[int] = mapped_column(default=0)
    hit_die_size: Mapped[int] = mapped_column(default=8, server_default="8")
    hit_dice_remaining: Mapped[int] = mapped_column(default=1, server_default="1")
    portrait_url: Mapped[str | None]

    # combat stats - real columns, queried/displayed individually
    hp: Mapped[int]
    max_hp: Mapped[int]
    temp_hp: Mapped[int] = mapped_column(default=0)
    ac: Mapped[int]
    speed: Mapped[int] = mapped_column(default=30)
    death_save_successes: Mapped[int] = mapped_column(default=0)
    death_save_failures: Mapped[int] = mapped_column(default=0)

    cr: Mapped[float] = mapped_column(default=0.0)
    conditions: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")

    # derived stats - stored for fast reads, recalculated on level-up
    proficiency_bonus: Mapped[int] = mapped_column(default=2)
    initiative: Mapped[int] = mapped_column(default=0)
    passive_perception: Mapped[int] = mapped_column(default=10)

    # companion flag — False = player's own character, True = AI-controlled party member
    is_companion: Mapped[bool] = mapped_column(default=False, server_default="false")
    is_dead: Mapped[bool] = mapped_column(default=False, server_default="false")

    # narrative voice — used by ally_ai to play this character
    bio: Mapped[str | None]
    personality: Mapped[str | None]
    voice_traits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    # spellcasting - None for non-spellcasters
    spellcasting_ability: Mapped[str | None]
    concentration: Mapped[str | None]  # name of currently concentrated spell, if any

    # class resources with limited uses (Action Surge, Ki, Rage, Superiority Dice, etc.)
    # shape: {"action_surge": {"current": 1, "max": 1, "resets_on": "short_rest"}, ...}
    resources: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    # JSONB - semi-structured data, always read as a unit
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    spell_slots: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    spells_known: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    saving_throw_proficiencies: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    skill_proficiencies: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    tool_proficiencies: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    features: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    feats: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    inventory: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    currency: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=lambda: {"gp": 0, "sp": 0, "cp": 0},
        server_default='{"gp": 0, "sp": 0, "cp": 0}',
    )
