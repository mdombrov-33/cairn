"""
Feat effect dispatcher.

Handlers here apply persistent, deterministic state changes (numeric bumps to
ability scores / AC / speed / max_hp, new proficiencies, new resources, new
spells). Feats whose effect is conditional or per-action — Sentinel, Sharpshooter,
Great Weapon Master, War Caster, fighting styles like Archery — have NO handler.
They're appended to char.feats and the LLM reads the SRD description at runtime.
"""

from collections.abc import Callable

import structlog

from cairn.db.models.character import Character
from cairn.domain.exceptions import ValidationError
from cairn.srd import get_feat

log = structlog.get_logger()

FeatHandler = Callable[[Character, dict], None]
FEAT_HANDLERS: dict[str, FeatHandler] = {}

_ABILITY_KEYS = {"str", "dex", "con", "int", "wis", "cha"}


def _register(*indices: str) -> Callable[[FeatHandler], FeatHandler]:
    """Register the same handler under multiple feat indices."""

    def decorator(fn: FeatHandler) -> FeatHandler:
        for index in indices:
            FEAT_HANDLERS[index] = fn
        return fn

    return decorator


# Helpers


def _bump_ability(char: Character, ability: str, by: int = 1, cap: int = 20) -> None:
    new_scores = dict(char.ability_scores)
    new_scores[ability] = min(cap, new_scores.get(ability, 10) + by)
    char.ability_scores = new_scores


def _require_ability_choice(options: dict, allowed: set[str]) -> str:
    ability = options.get("ability")
    if not isinstance(ability, str) or ability not in allowed:
        raise ValidationError(
            f"feat requires options.ability in {sorted(allowed)}, got {ability!r}"
        )
    return ability


def _grant_resource(char: Character, name: str, count: int, resets_on: str) -> None:
    resources = dict(char.resources or {})
    resources[name] = {"current": count, "max": count, "resets_on": resets_on}
    char.resources = resources


# Numeric bumps (no options)


@_register("alert")
def _alert(char: Character, options: dict) -> None:
    """+proficiency_bonus to initiative — applied by leveling.recompute_derived_stats
    based on the feat's presence in char.feats. No direct mutation here so that
    re-deriving initiative after future ability changes stays consistent."""
    return


@_register("defense")
def _defense(char: Character, options: dict) -> None:
    """Fighting style: +1 AC while wearing armor."""
    char.ac = char.ac + 1


@_register("mobile")
def _mobile(char: Character, options: dict) -> None:
    """+10 speed."""
    char.speed = char.speed + 10


@_register("tough")
def _tough(char: Character, options: dict) -> None:
    """+2 max HP per character level (retroactive at time of taking)."""
    bump = 2 * char.level
    char.max_hp = char.max_hp + bump
    char.hp = char.hp + bump


# Resource grants


@_register("lucky")
def _lucky(char: Character, options: dict) -> None:
    """3 luck points per long rest."""
    _grant_resource(char, "luck_points", count=3, resets_on="long_rest")


@_register("martial-adept")
def _martial_adept(char: Character, options: dict) -> None:
    """One superiority die per short rest. Maneuvers known are tracked behaviorally via SRD."""
    _grant_resource(char, "superiority_die", count=1, resets_on="short_rest")


# Half-feats: fixed +1 ability


@_register("durable")
def _durable(char: Character, options: dict) -> None:
    _bump_ability(char, "con")


@_register("keen-mind")
def _keen_mind(char: Character, options: dict) -> None:
    _bump_ability(char, "int")


@_register("actor")
def _actor(char: Character, options: dict) -> None:
    _bump_ability(char, "cha")


@_register("heavily-armored", "heavy-armor-master")
def _heavy_armor(char: Character, options: dict) -> None:
    _bump_ability(char, "str")


# Half-feats: choose one ability from a set


@_register("athlete", "lightly-armored", "moderately-armored", "weapon-master")
def _str_or_dex(char: Character, options: dict) -> None:
    ability = _require_ability_choice(options, {"str", "dex"})
    _bump_ability(char, ability)


@_register("tavern-brawler")
def _tavern_brawler(char: Character, options: dict) -> None:
    ability = _require_ability_choice(options, {"str", "con"})
    _bump_ability(char, ability)


@_register("observant")
def _observant(char: Character, options: dict) -> None:
    """+1 INT or WIS. +5 passive perception is applied by leveling.recompute_derived_stats."""
    ability = _require_ability_choice(options, {"int", "wis"})
    _bump_ability(char, ability)


@_register("resilient")
def _resilient(char: Character, options: dict) -> None:
    """+1 to chosen ability + save proficiency in that ability."""
    ability = _require_ability_choice(options, _ABILITY_KEYS)
    _bump_ability(char, ability)
    saves = list(char.saving_throw_proficiencies)
    if ability not in saves:
        saves.append(ability)
        char.saving_throw_proficiencies = saves


# Skill / spell picks


@_register("skilled")
def _skilled(char: Character, options: dict) -> None:
    """3 skill or tool proficiency picks."""
    skills = options.get("skills") or []
    if not isinstance(skills, list) or len(skills) != 3:
        raise ValidationError("skilled feat requires options.skills as a list of 3 entries")
    char.skill_proficiencies = list(dict.fromkeys(list(char.skill_proficiencies) + list(skills)))


@_register("magic-initiate")
def _magic_initiate(char: Character, options: dict) -> None:
    """2 cantrips + 1 first-level spell from a chosen class's list."""
    spells = options.get("spells") or []
    if not isinstance(spells, list) or len(spells) != 3:
        raise ValidationError(
            "magic-initiate requires options.spells: 2 cantrips + 1 first-level spell"
        )
    char.spells_known = list(char.spells_known) + list(spells)


@_register("spell-sniper")
def _spell_sniper(char: Character, options: dict) -> None:
    """Gain one cantrip from sorcerer/warlock/wizard list. Other effects are behavioral."""
    cantrip = options.get("cantrip")
    if not isinstance(cantrip, str) or not cantrip:
        raise ValidationError("spell-sniper requires options.cantrip (string)")
    char.spells_known = list(char.spells_known) + [cantrip]


# Entrypoint


def apply_feat(char: Character, feat_index: str, options: dict | None = None) -> None:
    """
    Apply a feat to a character.

    Looks up the feat in SRD (raises if unknown), runs the mechanical handler
    if registered, and always appends the feat to char.feats so it's visible
    to the LLM (which reads the SRD description for behavioral effects).
    """
    feat_data = get_feat(feat_index)
    if feat_data is None:
        raise ValidationError(f"unknown feat: {feat_index}")

    options = options or {}
    handler = FEAT_HANDLERS.get(feat_index)
    if handler is not None:
        handler(char, options)
    else:
        log.info("feat_no_handler", feat=feat_index, character_id=str(char.id))

    char.feats = list(char.feats) + [
        {"index": feat_index, "name": feat_data["name"], "options": options}
    ]
