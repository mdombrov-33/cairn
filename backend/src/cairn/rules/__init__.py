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
