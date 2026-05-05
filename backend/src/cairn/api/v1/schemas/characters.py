from typing import Any

from pydantic import BaseModel, Field

from cairn.api.v1.schemas.creatures import CreatureBase


class InventoryItem(BaseModel):
    name: str
    quantity: int = 1
    weight: float = 0
    notes: str = ""
    equipped: bool = False


class CharacterCreate(BaseModel):
    name: str
    race: str
    character_class: str
    background: str
    alignment: str | None = None
    subclass: str | None = None
    level: int = 1
    stats: dict[str, int]
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
    inventory: list[InventoryItem] = []
    currency: dict[str, int] = Field(default_factory=lambda: {"gp": 0, "sp": 0, "cp": 0})
    is_companion: bool = False
    bio: str | None = None
    personality: str | None = None
    voice_traits: dict[str, Any] = Field(default_factory=dict)


class CharacterResponse(CreatureBase):
    owner_id: str
    xp: int
    race: str
    background: str
    death_save_successes: int
    death_save_failures: int
    is_companion: bool
    bio: str | None
    personality: str | None
    voice_traits: dict[str, Any]
