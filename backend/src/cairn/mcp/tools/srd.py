from langchain_core.tools import tool

from cairn import srd as rules
from cairn.srd import _load_list


@tool
def lookup_spell(name: str) -> dict:
    """Look up a D&D 5e spell by name.

    Returns the full spell entry: level, school, casting time, range, components,
    duration, concentration, damage dice, saving throw type, area of effect,
    and which classes can cast it.

    Args:
        name: Spell name, e.g. "fireball", "cure wounds", "magic missile", "hold person".
    """
    spell = rules.get_spell(name)
    if spell is None:
        return {"error": f"Spell '{name}' not found in SRD. Check spelling or try a variant name."}
    return spell


@tool
def lookup_monster(name: str) -> dict:
    """Look up a monster's full stat block from the SRD.

    Returns AC, HP, speed, ability scores, saving throws, skills, damage immunities,
    senses, challenge rating, special abilities, and actions with attack bonus and damage dice.

    Args:
        name: Monster name, e.g. "goblin", "skeleton", "ogre", "adult-red-dragon".
    """
    monster = rules.get_monster(name)
    if monster is None:
        return {"error": f"Monster '{name}' not found in SRD."}
    return monster


@tool
def lookup_condition(name: str) -> dict:
    """Look up the mechanical rules for a condition (blinded, charmed, poisoned, prone, etc.).

    Args:
        name: Condition name, e.g. "blinded", "poisoned", "prone", "stunned", "unconscious".
    """
    condition = rules.get_condition(name)
    if condition is None:
        return {"error": f"Condition '{name}' not found in SRD."}
    return condition


@tool
def lookup_weapon(name: str) -> dict:
    """Look up a weapon's damage dice, damage type, range, and properties (finesse, versatile, reach, etc.).

    Use this before resolving weapon attacks to determine the correct damage expression
    and whether special properties apply (e.g. finesse allows using DEX instead of STR).

    Args:
        name: Weapon name, e.g. "longsword", "shortbow", "dagger", "hand-crossbow".
    """  # noqa: E501
    weapon = rules.get_weapon(name)
    if weapon is None:
        return {"error": f"Weapon '{name}' not found in SRD or is not a weapon."}
    return weapon


@tool
def lookup_race(name: str) -> dict:
    """Look up a race's traits, ability score bonuses, speed, and languages.

    Use during character creation to determine ability score increases and racial features.

    Args:
        name: Race name, e.g. "human", "elf", "dwarf", "half-elf", "tiefling".
    """
    race = rules.get_race(name)
    if race is None:
        return {"error": f"Race '{name}' not found in SRD."}
    return race


@tool
def lookup_class(name: str, level: int = 1) -> dict:
    """Look up a class's features and spell slots at a specific level.

    Returns base class info (hit die, proficiencies, saving throws) plus
    level-specific data (features unlocked, spell slots, class-specific bonuses like
    Action Surge uses or Sneak Attack dice).

    Args:
        name: Class name, e.g. "fighter", "wizard", "rogue", "cleric", "paladin".
        level: Character level 1-20.
    """
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
def lookup_feature(name: str) -> dict:
    """Look up a class feature's full description and mechanics.

    Use this when a character has a feature you need to understand — Action Surge,
    Sneak Attack, Rage, Wild Shape, Channel Divinity, Bardic Inspiration, etc.

    Args:
        name: Feature name, e.g. "action-surge-1-use", "sneak-attack", "rage", "second-wind".
    """
    feature = rules.get_feature(name)
    if feature is None:
        return {
            "error": f"Feature '{name}' not found. Try the index form e.g. 'action-surge-1-use'."
        }
    return feature


@tool
def lookup_trait(name: str) -> dict:
    """Look up a racial trait's description and mechanics.

    Use for racial abilities like Darkvision, Fey Ancestry, Gnome Cunning, Relentless Endurance.

    Args:
        name: Trait name, e.g. "darkvision", "fey-ancestry", "relentless-endurance".
    """
    trait = rules.get_trait(name)
    if trait is None:
        return {"error": f"Trait '{name}' not found."}
    return trait


@tool
def lookup_subclass(name: str) -> dict:
    """Look up a subclass's features and description.

    Args:
        name: Subclass index, e.g. "champion", "thief", "evocation", "life".
    """
    subclass = rules.get_subclass(name)
    if subclass is None:
        return {"error": f"Subclass '{name}' not found."}
    return subclass


@tool
def list_spells_for_class(class_name: str, max_level: int = 9) -> list[dict]:
    """List all SRD spells available to a class, optionally filtered by max spell level.

    Useful during character creation to choose spells known.

    Args:
        class_name: Class name, e.g. "wizard", "cleric", "sorcerer".
        max_level: Only return spells of this level or lower (1-9). Default 9 (all).
    """

    all_spells = _load_list("spells")
    key = class_name.lower()
    matching = [
        {"name": s["name"], "level": s["level"], "school": s.get("school", {}).get("name")}
        for s in all_spells
        if any(c["index"] == key for c in s.get("classes", [])) and s["level"] <= max_level
    ]
    return sorted(matching, key=lambda s: (s["level"], s["name"]))
