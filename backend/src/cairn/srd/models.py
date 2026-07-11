"""Typed records owned by the SRD catalog.

The source JSON contains many display-only fields.  Models keep those fields so
the HTTP and tool adapters can still return the source document unchanged,
while giving rules code a typed surface for the fields it owns.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SRDRecord(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    def as_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class Reference(SRDRecord):
    index: str
    name: str


class AbilityBonus(SRDRecord):
    ability_score: Reference
    bonus: int


class EquipmentEntry(SRDRecord):
    equipment: Reference
    quantity: int = 1


class ProficiencyChoice(SRDRecord):
    choose: int
    from_: dict[str, Any] = Field(alias="from")

    def skill_names(self) -> list[str]:
        return [
            option["item"]["name"].removeprefix("Skill: ")
            for option in self.from_.get("options", [])
            if option.get("option_type") == "reference" and option.get("item", {}).get("index", "").startswith("skill-")
        ]


class ClassSpellcasting(SRDRecord):
    spellcasting_ability: Reference | None = None


class ClassRecord(SRDRecord):
    index: str
    name: str
    hit_die: int
    proficiencies: list[Reference] = Field(default_factory=list)
    proficiency_choices: list[ProficiencyChoice] = Field(default_factory=list)
    saving_throws: list[Reference] = Field(default_factory=list)
    starting_equipment: list[EquipmentEntry] = Field(default_factory=list)
    spellcasting: ClassSpellcasting | None = None


class LevelSpellcasting(SRDRecord):
    cantrips_known: int | None = None
    spells_known: int | None = None

    def spell_slots(self) -> dict[str, int] | None:
        slots = {str(level): (self.model_extra or {}).get(f"spell_slots_level_{level}", 0) for level in range(1, 10)}
        return {level: count for level, count in slots.items() if isinstance(count, int) and count > 0} or None


class ClassLevelRecord(SRDRecord):
    index: str
    level: int
    ability_score_bonuses: int = 0
    features: list[Reference] = Field(default_factory=list)
    class_specific: dict[str, Any] = Field(default_factory=dict)
    spellcasting: LevelSpellcasting | None = None

    def spell_slots(self) -> dict[str, int] | None:
        if self.spellcasting is None:
            return None
        return self.spellcasting.spell_slots()


class RaceRecord(SRDRecord):
    index: str
    name: str
    speed: int = 30
    ability_bonuses: list[AbilityBonus] = Field(default_factory=list)
    traits: list[Reference] = Field(default_factory=list)


class SubraceRecord(SRDRecord):
    index: str
    name: str
    race: Reference
    ability_bonuses: list[AbilityBonus] = Field(default_factory=list)
    racial_traits: list[Reference] = Field(default_factory=list)


class BackgroundRecord(SRDRecord):
    index: str
    name: str
    skill_proficiencies: list[str] = Field(default_factory=list)
    tool_proficiencies: list[str] = Field(default_factory=list)


class EquipmentRecord(SRDRecord):
    index: str
    name: str
    equipment_category: Reference
    weapon_range: str | None = None
    properties: list[Reference] = Field(default_factory=list)
    damage: dict[str, Any] | None = None


class ArmorClassRecord(SRDRecord):
    base: int
    dex_bonus: bool
    max_bonus: int | None = None


class ArmorRecord(EquipmentRecord):
    armor_category: str
    armor_class: ArmorClassRecord


class MonsterAction(SRDRecord):
    name: str
    desc: str = ""
    attack_bonus: int = 0
    damage: list[dict[str, Any]] = Field(default_factory=list)


class MonsterRecord(SRDRecord):
    index: str
    name: str
    armor_class: list[dict[str, Any]]
    hit_points: int
    strength: int
    dexterity: int
    constitution: int
    intelligence: int
    wisdom: int
    charisma: int
    challenge_rating: float
    actions: list[MonsterAction] = Field(default_factory=list)


class SpellRecord(SRDRecord):
    index: str
    name: str
    level: int
    classes: list[Reference] = Field(default_factory=list)
    school: Reference | None = None


class NamedRecord(SRDRecord):
    index: str
    name: str


class FeatRecord(NamedRecord):
    type: str = "general"


class FeatureRecord(NamedRecord):
    level: int
    subclass: Reference | None = None


class SubclassRecord(NamedRecord):
    class_: Reference = Field(alias="class")


class ProficiencyRecord(NamedRecord):
    type: str
    races: list[Reference] = Field(default_factory=list)
