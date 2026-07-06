import uuid
from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base
from cairn.types import (
    AbilityScores,
    CompanionMeta,
    ConcentrationData,
    Currency,
    FeatEntry,
    FeatureEntry,
    InventoryItem,
    NarrativeProfile,
    Resource,
    SpellSlots,
)


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), index=True)
    owner_id: Mapped[str] = mapped_column(index=True)

    # identity
    name: Mapped[str]
    race: Mapped[str]
    subrace: Mapped[str | None]
    # Multiclass-ready shape: [{name, level, hit_dice_spent, subclass}]. v1 enforces
    # len(classes) == 1 in the service layer; multiclass unlocks in a later slice.
    classes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    background: Mapped[str]
    alignment: Mapped[str | None]
    level: Mapped[int] = mapped_column(default=1, server_default="1")
    xp: Mapped[int] = mapped_column(default=0, server_default="0")
    hit_die_size: Mapped[int] = mapped_column(default=8, server_default="8")
    hit_dice_remaining: Mapped[int] = mapped_column(default=1, server_default="1")
    portrait_url: Mapped[str | None]

    @property
    def class_name(self) -> str:
        """Primary class name. v1 single-class invariant: classes[0] is canonical."""
        return self.classes[0]["name"] if self.classes else ""

    @property
    def subclass_name(self) -> str | None:
        """Subclass of the primary class, if chosen."""
        return self.classes[0].get("subclass") if self.classes else None

    # combat stats - real columns, queried/displayed individually
    hp: Mapped[int]
    max_hp: Mapped[int]
    temp_hp: Mapped[int] = mapped_column(default=0, server_default="0")
    ac: Mapped[int]
    speed: Mapped[int] = mapped_column(default=30, server_default="30")
    death_save_successes: Mapped[int] = mapped_column(default=0, server_default="0")
    death_save_failures: Mapped[int] = mapped_column(default=0, server_default="0")

    cr: Mapped[float] = mapped_column(default=0.0, server_default="0")
    conditions: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")

    # derived stats - stored for fast reads, recalculated on level-up
    proficiency_bonus: Mapped[int] = mapped_column(default=2, server_default="2")
    initiative: Mapped[int] = mapped_column(default=0, server_default="0")
    passive_perception: Mapped[int] = mapped_column(default=10, server_default="10")

    # companion flag — False = player's own character, True = AI-controlled party member
    is_companion: Mapped[bool] = mapped_column(default=False, server_default="false")
    status: Mapped[str] = mapped_column(default="active", server_default="active")

    # Set when the character was created from a premade; NULL for custom-built PCs.
    # Drives intro_mode onboarding for brand-new custom characters.
    created_from_premade_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("premade_characters.id", ondelete="SET NULL")
    )

    # System-enforced advantage flag. Granted by DM for good roleplay, spent for advantage.
    has_inspiration: Mapped[bool] = mapped_column(default=False, server_default="false")

    # For is_companion=True: approval/mood/personal_goal/secret/approval_log.
    companion_meta: Mapped[CompanionMeta | None] = mapped_column(JSONB, nullable=True)

    # Deep prose identity — same shape as NPC.narrative_profile. Empty for PCs until authored.
    narrative_profile: Mapped[NarrativeProfile] = mapped_column(JSONB, default=dict, server_default="{}")

    # spellcasting - None for non-spellcasters
    spellcasting_ability: Mapped[str | None]
    # {spell_name, level, source_effect_id} — links to the effect this spell created.
    concentration: Mapped[ConcentrationData | None] = mapped_column(JSONB, nullable=True)
    prepared_spells: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")

    # class resources with limited uses (Action Surge, Ki, Rage, Superiority Dice, etc.)
    # Keyed by resource name → Resource shape.
    resources: Mapped[dict[str, Resource]] = mapped_column(JSONB, default=dict, server_default="{}")

    # JSONB — typed shapes live in cairn/types.py
    ability_scores: Mapped[AbilityScores] = mapped_column(JSONB, default=dict, server_default="{}")
    spell_slots: Mapped[SpellSlots | None] = mapped_column(JSONB)
    spells_known: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
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
