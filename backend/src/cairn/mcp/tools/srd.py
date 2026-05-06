from cairn import srd as rules
from cairn.mcp.tools.base import prop, tool
from cairn.srd import _load_list


@tool(
    "Look up a D&D 5e spell by name. Returns level, school, casting time, range, components, duration, concentration, damage dice, saving throw, and which classes can cast it.",  # noqa: E501
    {"name": prop("string", 'Spell name, e.g. "fireball", "cure wounds", "hold person".')},
    required=["name"],
)
async def lookup_spell(name: str) -> dict:
    spell = rules.get_spell(name)
    if spell is None:
        return {"error": f"Spell '{name}' not found in SRD. Check spelling or try a variant name."}
    return spell


@tool(
    "Look up a monster's full stat block from the SRD: AC, HP, speed, ability scores, saving throws, skills, challenge rating, special abilities, and actions.",  # noqa: E501
    {
        "name": prop(
            "string", 'Monster name, e.g. "goblin", "skeleton", "ogre", "adult-red-dragon".'
        )
    },
    required=["name"],
)
async def lookup_monster(name: str) -> dict:
    monster = rules.get_monster(name)
    if monster is None:
        return {"error": f"Monster '{name}' not found in SRD."}
    return monster


@tool(
    "Look up the mechanical rules for a condition (blinded, charmed, poisoned, prone, etc.).",
    {"name": prop("string", 'Condition name, e.g. "blinded", "poisoned", "prone", "stunned".')},
    required=["name"],
)
async def lookup_condition(name: str) -> dict:
    condition = rules.get_condition(name)
    if condition is None:
        return {"error": f"Condition '{name}' not found in SRD."}
    return condition


@tool(
    "Look up a weapon's damage dice, damage type, range, and properties (finesse, versatile, reach, etc.).",  # noqa: E501
    {
        "name": prop(
            "string", 'Weapon name, e.g. "longsword", "shortbow", "dagger", "hand-crossbow".'
        )
    },
    required=["name"],
)
async def lookup_weapon(name: str) -> dict:
    weapon = rules.get_weapon(name)
    if weapon is None:
        return {"error": f"Weapon '{name}' not found in SRD or is not a weapon."}
    return weapon


@tool(
    "Look up a race's traits, ability score bonuses, speed, and languages.",
    {"name": prop("string", 'Race name, e.g. "human", "elf", "dwarf", "half-elf", "tiefling".')},
    required=["name"],
)
async def lookup_race(name: str) -> dict:
    race = rules.get_race(name)
    if race is None:
        return {"error": f"Race '{name}' not found in SRD."}
    return race


@tool(
    "Look up a class's features and spell slots at a specific level.",
    {
        "name": prop("string", 'Class name, e.g. "fighter", "wizard", "rogue", "cleric".'),
        "level": prop("integer", "Character level 1-20.", default=1),
    },
    required=["name"],
)
async def lookup_class(name: str, level: int = 1) -> dict:
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


@tool(
    "Look up a class feature's full description and mechanics (Action Surge, Sneak Attack, Rage, Wild Shape, etc.).",  # noqa: E501
    {"name": prop("string", 'Feature name, e.g. "action-surge-1-use", "sneak-attack", "rage".')},
    required=["name"],
)
async def lookup_feature(name: str) -> dict:
    feature = rules.get_feature(name)
    if feature is None:
        return {
            "error": f"Feature '{name}' not found. Try the index form e.g. 'action-surge-1-use'."
        }
    return feature


@tool(
    "Look up a racial trait's description and mechanics (Darkvision, Fey Ancestry, Relentless Endurance, etc.).",  # noqa: E501
    {
        "name": prop(
            "string", 'Trait name, e.g. "darkvision", "fey-ancestry", "relentless-endurance".'
        )
    },
    required=["name"],
)
async def lookup_trait(name: str) -> dict:
    trait = rules.get_trait(name)
    if trait is None:
        return {"error": f"Trait '{name}' not found."}
    return trait


@tool(
    "Look up a subclass's features and description.",
    {"name": prop("string", 'Subclass index, e.g. "champion", "thief", "evocation", "life".')},
    required=["name"],
)
async def lookup_subclass(name: str) -> dict:
    subclass = rules.get_subclass(name)
    if subclass is None:
        return {"error": f"Subclass '{name}' not found."}
    return subclass


@tool(
    "List all SRD spells available to a class, optionally filtered by max spell level.",
    {
        "class_name": prop("string", 'Class name, e.g. "wizard", "cleric", "sorcerer".'),
        "max_level": prop(
            "integer", "Only return spells of this level or lower (1-9). Default 9.", default=9
        ),
    },
    required=["class_name"],
)
async def list_spells_for_class(class_name: str, max_level: int = 9) -> list[dict]:
    all_spells = _load_list("spells")
    key = class_name.lower()
    matching = [
        {"name": s["name"], "level": s["level"], "school": s.get("school", {}).get("name")}
        for s in all_spells
        if any(c["index"] == key for c in s.get("classes", [])) and s["level"] <= max_level
    ]
    return sorted(matching, key=lambda s: (s["level"], s["name"]))
