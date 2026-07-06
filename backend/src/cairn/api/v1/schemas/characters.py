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
    alignment: str
    # Deep prose identity (NarrativeProfile shape). Optional for PCs (authored later);
    # required for companions, who are roleplayed straight from it.
    narrative_profile: dict[str, Any] = Field(default_factory=dict)
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
        if self.is_companion:
            missing = {"name", "personality", "voice"} - set(self.narrative_profile)
            if missing:
                raise ValueError(f"companion narrative_profile requires: {sorted(missing)}")
        return self


class EquipRequest(BaseModel):
    item_name: str


class LevelUpRequest(BaseModel):
    hp_method: Literal["roll", "average"]
    hp_roll: int | None = None
    asi: dict[str, int] | None = None
    feat: str | None = None
    feat_options: dict[str, Any] | None = None
    new_spells: list[str] = Field(default_factory=list)
    subclass: str | None = None


class GrantXpRequest(BaseModel):
    amount: int


class LevelUpPreviewResponse(BaseModel):
    pending: bool
    target_level: int | None = None
    hp: dict | None = None
    asi_or_feat: bool | None = None
    subclass_required: bool | None = None
    available_subclasses: list[dict] | None = None
    available_feats: list[dict] | None = None
    new_features: list[dict] | None = None
    new_spell_slots: dict | None = None
    spells_to_choose: int | None = None
    proficiency_bonus: int | None = None


class XpAwardResponse(BaseModel):
    character: str
    xp: int
    level: int
    ready_to_level_up: bool


class PrepareSpellsRequest(BaseModel):
    spells: list[str]


class CharacterPatch(BaseModel):
    name: str | None = None
    narrative_profile: dict[str, Any] | None = None


class CharacterResponse(CreatureBase):
    # Character stores class/subclass inside the `classes` JSONB; expose them via the
    # derived properties (NPC, sharing CreatureBase, still has real class_/subclass columns).
    class_: str | None = Field(None, validation_alias="class_name", serialization_alias="class")
    subclass: str | None = Field(None, validation_alias="subclass_name")
    classes: list[dict[str, Any]] = Field(default_factory=list)
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
    has_inspiration: bool = False
    narrative_profile: dict[str, Any] = Field(default_factory=dict)
    companion_meta: dict[str, Any] | None = None
    prepared_spells: list[str] = []
