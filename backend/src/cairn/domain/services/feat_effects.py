"""
Handlers here apply persistent, deterministic state changes (numeric bumps to
ability scores / AC / speed / max_hp, new proficiencies, new resources, new
spells). Feats whose effect is conditional or per-action - Sentinel, Sharpshooter,
Great Weapon Master, War Caster, fighting styles like Archery — have NO handler.
They're appended to char.feats and the LLM reads the SRD description at runtime.
"""

from collections.abc import Callable
from typing import Any, Literal, cast

import structlog

from cairn.domain.characters import AbilityKey, AbilityScores, Resource
from cairn.domain.combat_rules import get_ability_score
from cairn.domain.exceptions import ValidationError
from cairn.srd.catalog import catalog

log = structlog.get_logger()

FeatHandler = Callable[[Any, dict], None]
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


def _bump_ability(char: Any, ability: str, by: int = 1, cap: int = 20) -> None:
    new_scores = cast(AbilityScores, {**char.ability_scores})
    current = get_ability_score(new_scores, ability)
    new_scores[cast(AbilityKey, ability)] = min(cap, current + by)
    char.ability_scores = new_scores


def _require_ability_choice(options: dict, allowed: set[str]) -> str:
    ability = options.get("ability")
    if not isinstance(ability, str) or ability not in allowed:
        raise ValidationError(f"feat requires options.ability in {sorted(allowed)}, got {ability!r}")
    return ability


def _grant_resource(
    char: Any,
    name: str,
    count: int,
    resets_on: Literal["short_rest", "long_rest"],
) -> None:
    resources = dict(char.resources or {})
    entry: Resource = {"current": count, "max": count, "resets_on": resets_on}
    resources[name] = entry
    char.resources = resources


def _grant_armor_prof(char: Any, categories: list[str]) -> None:
    profs = list(char.armor_proficiencies or [])
    for cat in categories:
        if cat not in profs:
            profs.append(cat)
    char.armor_proficiencies = profs


# Numeric bumps (no options)


@_register("alert")
def _alert(char: Any, options: dict) -> None:
    """+proficiency_bonus to initiative — applied by leveling.recompute_derived_stats
    based on the feat's presence in char.feats. No direct mutation here so that
    re-deriving initiative after future ability changes stays consistent."""
    return


@_register("defense")
def _defense(char: Any, options: dict) -> None:
    """Fighting style: +1 AC while wearing armor.
    The bonus is computed by ac.feat_ac_bonus() at derive_ac time, so it
    correctly appears/disappears as armor is equipped or removed. No mutation here."""
    return


@_register("mobile")
def _mobile(char: Any, options: dict) -> None:
    """+10 speed."""
    char.speed = char.speed + 10


@_register("tough")
def _tough(char: Any, options: dict) -> None:
    """+2 max HP per character level (retroactive at time of taking)."""
    bump = 2 * char.level
    char.max_hp = char.max_hp + bump
    char.hp = char.hp + bump


# Resource grants


@_register("lucky")
def _lucky(char: Any, options: dict) -> None:
    """3 luck points per long rest."""
    _grant_resource(char, "luck_points", count=3, resets_on="long_rest")


@_register("martial-adept")
def _martial_adept(char: Any, options: dict) -> None:
    """One superiority die per short rest. Maneuvers are stored in feat options."""
    maneuvers = options.get("maneuvers") or []
    if not isinstance(maneuvers, list) or len(maneuvers) != 2:
        raise ValidationError("martial-adept requires options.maneuvers as a list of 2 maneuver names")
    _grant_resource(char, "superiority_die", count=1, resets_on="short_rest")


# Half-feats: fixed +1 ability


@_register("durable")
def _durable(char: Any, options: dict) -> None:
    _bump_ability(char, "con")


@_register("keen-mind")
def _keen_mind(char: Any, options: dict) -> None:
    _bump_ability(char, "int")


@_register("actor")
def _actor(char: Any, options: dict) -> None:
    _bump_ability(char, "cha")


@_register("heavily-armored")
def _heavily_armored(char: Any, options: dict) -> None:
    _bump_ability(char, "str")
    _grant_armor_prof(char, ["heavy"])


@_register("heavy-armor-master")
def _heavy_armor_master(char: Any, options: dict) -> None:
    _bump_ability(char, "str")
    _grant_armor_prof(char, ["heavy"])
    # Damage tool checks this flag to reduce non-magical B/P/S damage by 3
    options["damage_reduction"] = 3


# Half-feats: choose one ability from a set


@_register("athlete")
def _athlete(char: Any, options: dict) -> None:
    ability = _require_ability_choice(options, {"str", "dex"})
    _bump_ability(char, ability)


@_register("lightly-armored")
def _lightly_armored(char: Any, options: dict) -> None:
    ability = _require_ability_choice(options, {"str", "dex"})
    _bump_ability(char, ability)
    _grant_armor_prof(char, ["light"])


@_register("moderately-armored")
def _moderately_armored(char: Any, options: dict) -> None:
    ability = _require_ability_choice(options, {"str", "dex"})
    _bump_ability(char, ability)
    _grant_armor_prof(char, ["medium", "shield"])


@_register("weapon-master")
def _weapon_master(char: Any, options: dict) -> None:
    ability = _require_ability_choice(options, {"str", "dex"})
    _bump_ability(char, ability)
    weapons = options.get("weapons") or []
    if not isinstance(weapons, list) or len(weapons) != 4:
        raise ValidationError("weapon-master requires options.weapons as a list of 4 weapon names")
    profs = list(char.weapon_proficiencies or [])
    for w in weapons:
        if w not in profs:
            profs.append(w)
    char.weapon_proficiencies = profs


@_register("tavern-brawler")
def _tavern_brawler(char: Any, options: dict) -> None:
    ability = _require_ability_choice(options, {"str", "con"})
    _bump_ability(char, ability)


@_register("observant")
def _observant(char: Any, options: dict) -> None:
    """+1 INT or WIS. +5 passive perception is applied by leveling.recompute_derived_stats."""
    ability = _require_ability_choice(options, {"int", "wis"})
    _bump_ability(char, ability)


@_register("resilient")
def _resilient(char: Any, options: dict) -> None:
    """+1 to chosen ability + save proficiency in that ability."""
    ability = _require_ability_choice(options, _ABILITY_KEYS)
    _bump_ability(char, ability)
    saves = list(char.saving_throw_proficiencies)
    if ability not in saves:
        saves.append(ability)
        char.saving_throw_proficiencies = saves


# Skill / spell picks


@_register("skilled")
def _skilled(char: Any, options: dict) -> None:
    """3 picks — each pick is a skill or a tool. Skills → skill_proficiencies, tools → tool_proficiencies."""
    picks = options.get("picks") or []
    if not isinstance(picks, list) or len(picks) != 3:
        raise ValidationError("skilled feat requires options.picks as a list of 3 {type, name} objects")
    skill_profs = list(char.skill_proficiencies or [])
    tool_profs = list(char.tool_proficiencies or [])
    for pick in picks:
        if not isinstance(pick, dict) or pick.get("type") not in {"skill", "tool"}:
            raise ValidationError("each skilled pick must be {type: 'skill'|'tool', name: str}")
        name = pick.get("name")
        if not name:
            raise ValidationError("each skilled pick must have a non-empty name")
        if pick["type"] == "skill":
            if name not in skill_profs:
                skill_profs.append(name)
        else:
            if name not in tool_profs:
                tool_profs.append(name)
    char.skill_proficiencies = skill_profs
    char.tool_proficiencies = tool_profs


@_register("magic-initiate")
def _magic_initiate(char: Any, options: dict) -> None:
    """2 cantrips + 1 first-level spell. Grants one free 1st-level cast per long rest."""
    spells = options.get("spells") or []
    if not isinstance(spells, list) or len(spells) != 3:
        raise ValidationError("magic-initiate requires options.spells: 2 cantrips + 1 first-level spell")
    char.spells_known = list(char.spells_known) + list(spells)
    _grant_resource(char, "magic_initiate_free_cast", count=1, resets_on="long_rest")


@_register("spell-sniper")
def _spell_sniper(char: Any, options: dict) -> None:
    """Gain one cantrip from sorcerer/warlock/wizard list. Other effects are behavioral."""
    cantrip = options.get("cantrip")
    if not isinstance(cantrip, str) or not cantrip:
        raise ValidationError("spell-sniper requires options.cantrip (string)")
    char.spells_known = list(char.spells_known) + [cantrip]


# Entrypoint


def apply_feat(char: Any, feat_index: str, options: dict | None = None) -> None:
    """
    Apply a feat to a character.

    Looks up the feat in SRD (raises if unknown), runs the mechanical handler
    if registered, and always appends the feat to char.feats so it's visible
    to the LLM (which reads the SRD description for behavioral effects).
    """
    feat_data = catalog.feat(feat_index)
    if feat_data is None:
        raise ValidationError(f"unknown feat: {feat_index}")

    options = options or {}
    handler = FEAT_HANDLERS.get(feat_index)
    if handler is not None:
        handler(char, options)
    else:
        log.info("feat_no_handler", feat=feat_index, character_id=str(char.id))

    char.feats = list(char.feats) + [{"index": feat_index, "name": feat_data.name, "options": options}]
