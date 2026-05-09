import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache
def _load_list(name: str) -> list[dict]:
    return json.loads((_DIR / f"{name}.json").read_text())


@lru_cache
def _load_dict(name: str) -> dict[str, dict]:
    """Index a list-based SRD file by 'index' field."""
    return {item["index"]: item for item in _load_list(name)}


def get_condition(name: str) -> dict | None:
    key = name.lower().replace(" ", "-")
    return _load_dict("conditions").get(key)


def get_spell(name: str) -> dict | None:
    key = name.lower().replace(" ", "-").replace("'", "")
    return _load_dict("spells").get(key)


def get_monster(name: str) -> dict | None:
    key = name.lower().replace(" ", "-")
    return _load_dict("monsters").get(key)


def get_race(name: str) -> dict | None:
    key = name.lower().replace(" ", "-")
    return _load_dict("races").get(key)


def get_class(name: str) -> dict | None:
    return _load_dict("classes").get(name.lower())


def get_class_levels(name: str) -> list[dict]:
    data = json.loads((_DIR / "class_levels.json").read_text())
    return data.get(name.lower(), [])


def get_weapon(name: str) -> dict | None:
    key = name.lower().replace(" ", "-")
    item = _load_dict("equipment").get(key)
    if item and item.get("equipment_category", {}).get("index") == "weapon":
        return item
    return None


def get_all_conditions() -> list[dict]:
    return _load_list("conditions")


@lru_cache
def _all_feats() -> dict[str, dict]:
    """Merge 2024 SRD feats with PHB supplement, PHB wins on conflict."""
    srd = {item["index"]: item for item in _load_list("feats")}
    phb = {item["index"]: item for item in _load_list("feats_phb")}
    return {**srd, **phb}


def get_feat(name: str) -> dict | None:
    key = name.lower().replace(" ", "-").replace("'", "")
    return _all_feats().get(key)


def list_all_feats() -> list[dict]:
    return list(_all_feats().values())


def get_feature(name: str) -> dict | None:
    key = (
        name.lower().replace(" ", "-").replace("(", "").replace(")", "").replace(",", "").strip("-")
    )  # noqa: E501
    return _load_dict("features").get(key)


def get_trait(name: str) -> dict | None:
    key = name.lower().replace(" ", "-")
    return _load_dict("traits").get(key)


def get_subclass(name: str) -> dict | None:
    key = name.lower().replace(" ", "-")
    return _load_dict("subclasses").get(key)


def list_subclasses_for_class(class_index: str) -> list[dict]:
    return [s for s in _load_list("subclasses") if s.get("class", {}).get("index") == class_index]


def list_spells_for_character(spells_known: list[str]) -> list[dict]:
    """Return full spell data for each spell a character knows."""
    result = []
    for name in spells_known:
        data = get_spell(name)
        if data:
            result.append(data)
    return result


def list_races() -> list[dict]:
    return _load_list("races")


def list_subraces() -> list[dict]:
    return _load_list("subraces")


def get_subrace(index: str) -> dict | None:
    return _load_dict("subraces").get(index)


def list_backgrounds() -> list[dict]:
    return _load_list("backgrounds")


def get_background(index: str) -> dict | None:
    return _load_dict("backgrounds").get(index)


def list_classes() -> list[dict]:
    return _load_list("classes")


def list_skills() -> list[dict]:
    return _load_list("skills")


def list_languages() -> list[dict]:
    return _load_list("languages")


def list_equipment(category: str | None = None) -> list[dict]:
    items = _load_list("equipment")
    if category:
        items = [i for i in items if i.get("equipment_category", {}).get("index") == category]
    return items


def list_monsters(max_cr: float | None = None) -> list[dict]:
    monsters = _load_list("monsters")
    if max_cr is not None:
        monsters = [m for m in monsters if m.get("challenge_rating", 0) <= max_cr]
    return monsters


def list_spells(class_index: str | None = None, max_level: int | None = None) -> list[dict]:
    spells = _load_list("spells")
    if class_index:
        spells = [
            s for s in spells if any(c.get("index") == class_index for c in s.get("classes", []))
        ]
    if max_level is not None:
        spells = [s for s in spells if s.get("level", 0) <= max_level]
    return spells
