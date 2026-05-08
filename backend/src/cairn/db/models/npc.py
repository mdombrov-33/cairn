import uuid
from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base


class NPC(Base):
    __tablename__ = "npcs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))

    # Identity
    name: Mapped[str]
    race: Mapped[str | None]
    class_: Mapped[str | None] = mapped_column("class")
    subclass: Mapped[str | None]
    background: Mapped[str | None]
    alignment: Mapped[str | None]
    level: Mapped[int] = mapped_column(default=1)
    portrait_url: Mapped[str | None]

    # Narrative / voice
    bio: Mapped[str]
    personality: Mapped[str]
    voice_traits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    disposition: Mapped[str] = mapped_column(default="neutral")

    # Combat stats
    ac: Mapped[int] = mapped_column(default=10)
    max_hp: Mapped[int] = mapped_column(default=1)
    hp: Mapped[int] = mapped_column(default=1)
    temp_hp: Mapped[int] = mapped_column(default=0)
    speed: Mapped[int] = mapped_column(default=30)
    proficiency_bonus: Mapped[int] = mapped_column(default=2)
    initiative: Mapped[int] = mapped_column(default=0)
    passive_perception: Mapped[int] = mapped_column(default=10)

    # NPC-specific combat
    cr: Mapped[float] = mapped_column(default=0.0)
    xp_value: Mapped[int] = mapped_column(default=0)
    conditions: Mapped[list[Any]] = mapped_column(JSONB, default=list)

    # Spellcasting
    spellcasting_ability: Mapped[str | None]
    spell_slots: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    spells_known: Mapped[list[Any]] = mapped_column(JSONB, default=list)

    # JSONB — matches Character field names exactly
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    saving_throw_proficiencies: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    skill_proficiencies: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    features: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    feats: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    inventory: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    currency: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=lambda: {"gp": 0, "sp": 0, "cp": 0}
    )
