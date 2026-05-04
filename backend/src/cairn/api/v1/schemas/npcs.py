import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NPCResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    campaign_id: uuid.UUID

    # Identity
    name: str
    race: str | None
    class_: str | None = Field(None, alias="class")
    subclass: str | None
    background: str | None
    alignment: str | None
    level: int
    portrait_url: str | None

    # Narrative / voice
    bio: str
    personality: str
    voice_traits: dict[str, Any]
    disposition: str

    # Combat stats
    ac: int
    max_hp: int
    current_hp: int
    temp_hp: int
    speed: int
    death_save_successes: int
    death_save_failures: int
    proficiency_bonus: int
    initiative: int
    passive_perception: int

    # NPC-specific
    cr: float
    xp_value: int
    conditions: list[str]

    # Spellcasting
    spellcasting_ability: str | None
    spell_slots: dict[str, Any] | None
    spells_known: list[Any]

    # JSONB
    stats: dict[str, Any]
    saving_throw_proficiencies: list[Any]
    skill_proficiencies: list[Any]
    features: list[Any]
    inventory: list[Any]
    currency: dict[str, Any]
