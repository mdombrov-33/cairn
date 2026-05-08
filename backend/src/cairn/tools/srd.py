from typing import Annotated

from langchain_core.tools import tool

from cairn import srd as rules
from cairn.srd import _load_list


@tool
async def lookup_spell(
    name: Annotated[str, 'Spell name, e.g. "fireball", "cure wounds", "hold person".'],
) -> dict:
    """Look up a D&D 5e spell by name. Returns level, school, casting time, range, components, duration, concentration, damage dice, saving throw, and which classes can cast it."""  # noqa: E501
    spell = rules.get_spell(name)
    if spell is None:
        return {"error": f"Spell '{name}' not found in SRD. Check spelling or try a variant name."}
    return spell


@tool
async def lookup_monster(
    name: Annotated[str, 'Monster name, e.g. "goblin", "skeleton", "ogre", "adult-red-dragon".'],
) -> dict:
    """Look up a monster's full stat block from the SRD: AC, HP, speed, ability scores, saving throws, skills, challenge rating, special abilities, and actions."""  # noqa: E501
    monster = rules.get_monster(name)
    if monster is None:
        return {"error": f"Monster '{name}' not found in SRD."}
    return monster


@tool
async def lookup_condition(
    name: Annotated[str, 'Condition name, e.g. "blinded", "poisoned", "prone", "stunned".'],
) -> dict:
    """Look up the mechanical rules for a condition (blinded, charmed, poisoned, prone, etc.)."""
    condition = rules.get_condition(name)
    if condition is None:
        return {"error": f"Condition '{name}' not found in SRD."}
    return condition


@tool
async def lookup_weapon(
    name: Annotated[str, 'Weapon name, e.g. "longsword", "shortbow", "dagger", "hand-crossbow".'],
) -> dict:
    """Look up a weapon's damage dice, damage type, range, and properties (finesse, versatile, reach, etc.)."""  # noqa: E501
    weapon = rules.get_weapon(name)
    if weapon is None:
        return {"error": f"Weapon '{name}' not found in SRD or is not a weapon."}
    return weapon


@tool
async def lookup_race(
    name: Annotated[str, 'Race name, e.g. "human", "elf", "dwarf", "half-elf", "tiefling".'],
) -> dict:
    """Look up a race's traits, ability score bonuses, speed, and languages."""
    race = rules.get_race(name)
    if race is None:
        return {"error": f"Race '{name}' not found in SRD."}
    return race


@tool
async def lookup_class(
    name: Annotated[str, 'Class name, e.g. "fighter", "wizard", "rogue", "cleric".'],
    level: Annotated[int, "Character level 1-20."] = 1,
) -> dict:
    """Look up a class's features and spell slots at a specific level."""
    cls = rules.get_class(name)
    if cls is None:
        return {"error": f"Class '{name}' not found in SRD."}
    all_levels = rules.get_class_levels(name)
    level_data = next((lvl for lvl in all_levels if lvl["level"] == level), None)
    return {
        "class": {
            "name": cls["name"],
            "hit_die": cls["hit_die"],
            "saving_throws": [st["name"] for st in cls.get("saving_throws", [])],
        },
        "at_level": level_data,
    }


@tool
async def lookup_feature(
    name: Annotated[str, 'Feature name, e.g. "action-surge-1-use", "sneak-attack", "rage".'],
) -> dict:
    """Look up a class feature's full description and mechanics (Action Surge, Sneak Attack, Rage, Wild Shape, etc.)."""  # noqa: E501
    feature = rules.get_feature(name)
    if feature is None:
        return {
            "error": f"Feature '{name}' not found. Try the index form e.g. 'action-surge-1-use'."
        }
    return feature


@tool
async def lookup_trait(
    name: Annotated[str, 'Trait name, e.g. "darkvision", "fey-ancestry", "relentless-endurance".'],
) -> dict:
    """Look up a racial trait's description and mechanics (Darkvision, Fey Ancestry, Relentless Endurance, etc.)."""  # noqa: E501
    trait = rules.get_trait(name)
    if trait is None:
        return {"error": f"Trait '{name}' not found."}
    return trait


@tool
async def lookup_subclass(
    name: Annotated[str, 'Subclass index, e.g. "champion", "thief", "evocation", "life".'],
) -> dict:
    """Look up a subclass's features and description."""
    subclass = rules.get_subclass(name)
    if subclass is None:
        return {"error": f"Subclass '{name}' not found."}
    return subclass


@tool
async def list_spells_for_class(
    class_name: Annotated[str, 'Class name, e.g. "wizard", "cleric", "sorcerer".'],
    max_level: Annotated[int, "Only return spells of this level or lower (1-9). Default 9."] = 9,
) -> list:
    """List all SRD spells available to a class, optionally filtered by max spell level."""
    all_spells = _load_list("spells")
    key = class_name.lower()
    matching = [
        {"name": s["name"], "level": s["level"], "school": s.get("school", {}).get("name")}
        for s in all_spells
        if any(c["index"] == key for c in s.get("classes", [])) and s["level"] <= max_level
    ]
    return sorted(matching, key=lambda s: (s["level"], s["name"]))
