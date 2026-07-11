"""Compatibility adapters for SRD HTTP and tool consumers.

Rules code should import typed records from :mod:`cairn.srd.catalog` instead.
"""

from typing import Any

from cairn.srd.catalog import catalog


def _json(record: Any) -> dict[str, Any] | None:
    return record.as_json() if record else None


def get_condition(name: str) -> dict[str, Any] | None:
    return _json(catalog.named("conditions", name))


def get_spell(name: str) -> dict[str, Any] | None:
    return _json(catalog.spell(name))


def get_monster(name: str) -> dict[str, Any] | None:
    return _json(catalog.monster(name))


def get_race(name: str) -> dict[str, Any] | None:
    return _json(catalog.race(name))


def get_class(name: str) -> dict[str, Any] | None:
    return _json(catalog.class_(name))


def get_class_levels(name: str) -> list[dict[str, Any]]:
    return [record.as_json() for record in catalog.class_levels(name)]


def get_equipment(index: str) -> dict[str, Any] | None:
    return _json(catalog.equipment_item(index))


def get_weapon(name: str) -> dict[str, Any] | None:
    return _json(catalog.weapon(name))


def get_armor(index: str) -> dict[str, Any] | None:
    return _json(catalog.armor(index))


def get_proficiencies_for_race(race_index: str, subrace_index: str | None = None) -> list[dict[str, Any]]:
    return [record.as_json() for record in catalog.proficiencies_for_race(race_index, subrace_index)]


def get_all_conditions() -> list[dict[str, Any]]:
    return [record.as_json() for record in catalog.named_records("conditions")]


def get_feat(name: str) -> dict[str, Any] | None:
    return _json(catalog.feat(name))


def list_all_feats() -> list[dict[str, Any]]:
    return [record.as_json() for record in catalog.feats]


def get_feature(name: str) -> dict[str, Any] | None:
    return _json(catalog.feature(name))


def get_trait(name: str) -> dict[str, Any] | None:
    return _json(catalog.named("traits", name))


def get_subclass(name: str) -> dict[str, Any] | None:
    return _json(catalog.subclass(name))


def get_subclass_features_at_level(subclass_index: str, level: int) -> list[dict[str, Any]]:
    return [record.as_json() for record in catalog.subclass_features_at_level(subclass_index, level)]


def list_subclasses_for_class(class_index: str) -> list[dict[str, Any]]:
    return [record.as_json() for record in catalog.subclasses() if record.class_.index == class_index]


def list_spells_for_character(spells_known: list[str]) -> list[dict[str, Any]]:
    return [record.as_json() for name in spells_known if (record := catalog.spell(name))]


def list_races() -> list[dict[str, Any]]:
    return [record.as_json() for record in catalog.races]


def list_subraces() -> list[dict[str, Any]]:
    return [record.as_json() for record in catalog.subraces]


def get_subrace(index: str) -> dict[str, Any] | None:
    return _json(catalog.subrace(index))


def list_backgrounds() -> list[dict[str, Any]]:
    return [record.as_json() for record in catalog.backgrounds]


def get_background(index: str) -> dict[str, Any] | None:
    return _json(catalog.background(index))


def list_classes() -> list[dict[str, Any]]:
    return [record.as_json() for record in catalog.classes]


def _named_list(file_name: str) -> list[dict[str, Any]]:
    return [record.as_json() for record in catalog.named_records(file_name)]


def list_skills() -> list[dict[str, Any]]:
    return _named_list("skills")


def list_languages() -> list[dict[str, Any]]:
    return _named_list("languages")


def list_equipment(category: str | None = None) -> list[dict[str, Any]]:
    records = catalog.equipment
    if category:
        records = tuple(record for record in records if record.equipment_category.index == category)
    return [record.as_json() for record in records]


def list_monsters(max_cr: float | None = None) -> list[dict[str, Any]]:
    records = catalog.monsters
    if max_cr is not None:
        records = tuple(record for record in records if record.challenge_rating <= max_cr)
    return [record.as_json() for record in records]


def list_spells(class_index: str | None = None, max_level: int | None = None) -> list[dict[str, Any]]:
    records = catalog.spells
    if class_index:
        records = tuple(record for record in records if any(cls.index == class_index for cls in record.classes))
    if max_level is not None:
        records = tuple(record for record in records if record.level <= max_level)
    return [record.as_json() for record in records]
