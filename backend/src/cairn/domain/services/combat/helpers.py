from typing import cast

from cairn.types import (
    AbilityKey,
    AbilityScores,
    Combatant,
    CombatState,
    MonsterCombatant,
)

_ABILITY_KEYS: frozenset[str] = frozenset({"str", "dex", "con", "int", "wis", "cha"})


def get_ability_score(scores: AbilityScores, ability: str, default: int = 10) -> int:
    """Look up an ability score with a runtime string key. Returns default if
    the key isn't one of the six 5e abilities. Single source of truth for the
    "runtime string into TypedDict" narrowing — keeps the cast confined."""
    if ability not in _ABILITY_KEYS:
        return default
    return scores[cast(AbilityKey, ability)]


def empty_combat_state() -> CombatState:
    """Fresh empty CombatState; used as a fallback when combat isn't active.
    Returning a new dict every call avoids accidental mutation of a shared sentinel."""
    return {"round": 0, "turn_index": 0, "combatants": [], "effects": []}


ABILITY_LONG = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}

SKILL_ABILITY: dict[str, str] = {
    "athletics": "str",
    "acrobatics": "dex",
    "sleight of hand": "dex",
    "stealth": "dex",
    "arcana": "int",
    "history": "int",
    "investigation": "int",
    "nature": "int",
    "religion": "int",
    "animal handling": "wis",
    "insight": "wis",
    "medicine": "wis",
    "perception": "wis",
    "survival": "wis",
    "deception": "cha",
    "intimidation": "cha",
    "performance": "cha",
    "persuasion": "cha",
}


def find_combatant(state: CombatState, combatant_id: str) -> Combatant | None:
    for c in state.get("combatants", []):
        if c["id"] == combatant_id:
            return c
    return None


def find_monster(state: CombatState, combatant_id: str) -> MonsterCombatant | None:
    """Look up a combatant and narrow it to a monster (inline-stat) combatant.

    Monster stats (hp/ac/srd_index) live on the combatant dict; characters and
    npcs reference their DB row instead. Callers in monster-only branches use
    this so the checker can see the inline fields are present."""
    c = find_combatant(state, combatant_id)
    if c is not None and c["type"] == "monster":
        return c
    return None


def exhaustion_level(conditions: list[str]) -> int:
    for c in conditions:
        if isinstance(c, str) and c.startswith("exhaustion-"):
            try:
                return int(c.split("-", 1)[1])
            except ValueError:
                pass
    return 0
