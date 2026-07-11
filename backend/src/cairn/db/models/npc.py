import uuid
from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base
from cairn.domain.characters import (
    AbilityScores,
    Currency,
    FeatEntry,
    FeatureEntry,
    InventoryItem,
    SpellSlots,
)
from cairn.domain.combat import ConcentrationData
from cairn.domain.narrative import NarrativeProfile


class NPC(Base):
    __tablename__ = "npcs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))

    # Identity
    name: Mapped[str]
    race: Mapped[str | None]
    class_: Mapped[str | None] = mapped_column("class")
    subclass: Mapped[str | None]
    background: Mapped[str | None]
    alignment: Mapped[str | None]
    level: Mapped[int] = mapped_column(default=1, server_default="1")
    portrait_url: Mapped[str | None]

    # Deep prose identity — who they are, how they talk, history, goals, prejudices, secrets.
    narrative_profile: Mapped[NarrativeProfile] = mapped_column(JSONB, default=dict, server_default="{}")
    disposition: Mapped[str] = mapped_column(default="neutral", server_default="neutral")
    # Narrative importance to the plot (NOT authoring depth): major | recurring | background.
    tier: Mapped[str] = mapped_column(default="background", server_default="background")
    # Cheap promotion trigger: background→recurring auto-promotes at >=3 dialogue exchanges.
    dialogue_exchange_count: Mapped[int] = mapped_column(default=0, server_default="0")

    # Recruitment: an unrecruited companion lives as an NPC. `recruitable` marks predefined
    # companions (any recurring NPC is also dynamically recruitable). `companion_sheet` is the
    # authored playable sheet copied on conversion (null → the builder stats up a dynamic recruit).
    # `recruitment_condition` records a `conditional` recruiter outcome until it's met.
    recruitable: Mapped[bool] = mapped_column(default=False, server_default="false")
    companion_sheet: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    recruitment_condition: Mapped[str | None]

    # Combat stats
    ac: Mapped[int] = mapped_column(default=10, server_default="10")
    max_hp: Mapped[int] = mapped_column(default=1, server_default="1")
    hp: Mapped[int] = mapped_column(default=1, server_default="1")
    temp_hp: Mapped[int] = mapped_column(default=0, server_default="0")
    speed: Mapped[int] = mapped_column(default=30, server_default="30")
    proficiency_bonus: Mapped[int] = mapped_column(default=2, server_default="2")
    initiative: Mapped[int] = mapped_column(default=0, server_default="0")
    passive_perception: Mapped[int] = mapped_column(default=10, server_default="10")

    # NPC-specific combat
    cr: Mapped[float] = mapped_column(default=0.0, server_default="0")
    xp_value: Mapped[int] = mapped_column(default=0, server_default="0")
    conditions: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")

    # Spellcasting
    spellcasting_ability: Mapped[str | None]
    spell_slots: Mapped[SpellSlots | None] = mapped_column(JSONB)
    spells_known: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # {spell_name, level, source_effect_id} — same shape as Character.concentration.
    concentration: Mapped[ConcentrationData | None] = mapped_column(JSONB, nullable=True)

    # JSONB — typed shapes live in cairn/domain/characters.py.
    ability_scores: Mapped[AbilityScores] = mapped_column(JSONB, default=dict, server_default="{}")
    saving_throw_proficiencies: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    skill_proficiencies: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    tool_proficiencies: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    armor_proficiencies: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    weapon_proficiencies: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    features: Mapped[list[FeatureEntry]] = mapped_column(JSONB, default=list, server_default="[]")
    feats: Mapped[list[FeatEntry]] = mapped_column(JSONB, default=list, server_default="[]")
    inventory: Mapped[list[InventoryItem]] = mapped_column(JSONB, default=list, server_default="[]")
    currency: Mapped[Currency] = mapped_column(
        JSONB,
        default=lambda: {"gp": 0, "sp": 0, "cp": 0},
        server_default='{"gp": 0, "sp": 0, "cp": 0}',
    )
