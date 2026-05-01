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
    portrait_url: Mapped[str | None]

    # combat stats - real columns, queried/displayed individually
    hp: Mapped[int]
    max_hp: Mapped[int]
    temp_hp: Mapped[int] = mapped_column(default=0)
    ac: Mapped[int]
    speed: Mapped[int] = mapped_column(default=30)
    death_save_successes: Mapped[int] = mapped_column(default=0)
    death_save_failures: Mapped[int] = mapped_column(default=0)

    # derived stats - stored for fast reads, recalculated on level-up
    proficiency_bonus: Mapped[int] = mapped_column(default=2)
    initiative: Mapped[int] = mapped_column(default=0)
    passive_perception: Mapped[int] = mapped_column(default=10)

    # spellcasting - None for non-spellcasters
    spellcasting_ability: Mapped[str | None]

    # JSONB - semi-structured data, always read as a unit
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    spell_slots: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    spells_known: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    saving_throw_proficiencies: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    skill_proficiencies: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    features: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    inventory: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    currency: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=lambda: {"gp": 0, "sp": 0, "cp": 0}
    )
