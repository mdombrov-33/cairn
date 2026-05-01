import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CharacterCreate(BaseModel):
    name: str
    race: str
    character_class: str
    background: str
    alignment: str | None = None
    subclass: str | None = None
    level: int = 1
    stats: dict[str, int]  # {"str": 16, "dex": 12, "con": 14, "int": 8, "wis": 10, "cha": 13}
    hp: int
    max_hp: int
    ac: int
    speed: int = 30
    saving_throw_proficiencies: list[str] = []
    skill_proficiencies: list[str] = []
    spellcasting_ability: str | None = None
    spell_slots: dict[str, Any] | None = None
    spells_known: list[str] = []
    features: list[str] = []
    inventory: list[Any] = []
    currency: dict[str, int] = Field(default_factory=lambda: {"gp": 0, "sp": 0, "cp": 0})


class CharacterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    owner_id: str
    name: str
    race: str
    character_class: str = Field(validation_alias="class_")
    subclass: str | None
    background: str
    alignment: str | None
    level: int
    xp: int
    portrait_url: str | None

    # combat stats
    hp: int
    max_hp: int
    temp_hp: int
    ac: int
    speed: int
    death_save_successes: int
    death_save_failures: int

    # derived
    proficiency_bonus: int
    initiative: int
    passive_perception: int

    # spellcasting
    spellcasting_ability: str | None
    spell_slots: dict[str, Any] | None
    spells_known: list[Any]

    # proficiencies and features
    saving_throw_proficiencies: list[Any]
    skill_proficiencies: list[Any]
    features: list[Any]
    inventory: list[Any]
    currency: dict[str, Any]
    stats: dict[str, Any]
