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


def list_spells_for_character(spells_known: list[str]) -> list[dict]:
    """Return full spell data for each spell a character knows."""
    result = []
    for name in spells_known:
        data = get_spell(name)
        if data:
            result.append(data)
    return result
