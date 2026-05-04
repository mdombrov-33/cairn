import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CreatureBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    campaign_id: uuid.UUID

    # Identity
    name: str
    class_: str | None = Field(None, validation_alias="class_", serialization_alias="class")
    subclass: str | None
    alignment: str | None
    level: int
    portrait_url: str | None

    # Combat stats
    hp: int
    max_hp: int
    temp_hp: int
    ac: int
    speed: int
    proficiency_bonus: int
    initiative: int
    passive_perception: int
    cr: float
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
