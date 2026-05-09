from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from cairn.api.v1.schemas.creatures import CreatureBase

_STANDARD_ARRAY = sorted([15, 14, 13, 12, 10, 8], reverse=True)
_ABILITY_KEYS = {"str", "dex", "con", "int", "wis", "cha"}


class CharacterCreate(BaseModel):
    name: str
    race: str
    character_class: str
    background: str
    ability_scores: dict[str, int]
    skill_choices: list[str]
    ac: int
    alignment: str
    bio: str
    personality: str
    voice_traits: dict[str, Any] = Field(default_factory=dict)
    subrace: str | None = None
    subclass: str | None = None
    is_companion: bool = False
    spell_choices: list[str] | None = None

    @model_validator(mode="after")
    def _validate_ability_scores(self) -> CharacterCreate:
        keys = set(self.ability_scores.keys())
        if keys != _ABILITY_KEYS:
            raise ValueError(f"ability_scores must have keys: {sorted(_ABILITY_KEYS)}")
        if sorted(self.ability_scores.values(), reverse=True) != _STANDARD_ARRAY:
            raise ValueError(f"ability_scores must use standard array {_STANDARD_ARRAY}")
        return self

    @model_validator(mode="after")
    def _validate_companion(self) -> CharacterCreate:
        if self.is_companion and not self.voice_traits:
            raise ValueError("voice_traits required for companions")
        return self


class CharacterResponse(CreatureBase):
    owner_id: str
    xp: int
    race: str
    subrace: str | None
    background: str
    status: Literal["active", "dead", "abandoned"]
    hit_die_size: int
    hit_dice_remaining: int
    death_save_successes: int
    death_save_failures: int
    resources: dict[str, Any]
    is_companion: bool
    bio: str | None
    personality: str | None
    voice_traits: dict[str, Any]
