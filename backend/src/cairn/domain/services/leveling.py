import math
import uuid
from dataclasses import dataclass, field
from typing import cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.character import Character
from cairn.db.queries import characters as character_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import ConflictError, ValidationError
from cairn.domain.services import feat_effects
from cairn.domain.services.ac import AcInput, derive_ac
from cairn.domain.services.combat.helpers import get_ability_score
from cairn.srd import (
    get_class_levels,
    get_feat,
    get_subclass,
    list_all_feats,
    list_subclasses_for_class,
)
from cairn.types import AbilityKey, AbilityScores, FeatureEntry

log = structlog.get_logger()


# 5e XP table (levels 1-20). Index = level - 1.
XP_THRESHOLDS: list[int] = [
    0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000,
    85000, 100000, 120000, 140000, 165000, 195000, 225000, 265000, 305000, 355000,
]  # fmt: skip


# When each class first chooses a subclass.
SUBCLASS_LEVEL: dict[str, int] = {
    "barbarian": 3,
    "bard": 3,
    "cleric": 1,
    "druid": 2,
    "fighter": 3,
    "monk": 3,
    "paladin": 3,
    "ranger": 3,
    "rogue": 3,
    "sorcerer": 1,
    "warlock": 1,
    "wizard": 2,
}


# class_specific keys → (canonical resource name, reset trigger).
# Anything not listed is treated as a passive scaling stat (read by LLM at runtime),
# not a consumable resource.
RESOURCE_MAP: dict[str, tuple[str, str]] = {
    "rage_count": ("rage", "long_rest"),
    "ki_points": ("ki_points", "short_rest"),
    "action_surges": ("action_surge", "short_rest"),
    "indomitable_uses": ("indomitable", "long_rest"),
    "channel_divinity_charges": ("channel_divinity", "short_rest"),
    "sorcery_points": ("sorcery_points", "long_rest"),
}


_ABILITY_KEYS = {"str", "dex", "con", "int", "wis", "cha"}


# Pure helpers


def level_for_xp(xp: int) -> int:
    for i in range(len(XP_THRESHOLDS) - 1, -1, -1):
        if xp >= XP_THRESHOLDS[i]:
            return i + 1
    return 1


def has_pending_level_up(char: Character) -> bool:
    return level_for_xp(char.xp) > char.level


def _ability_modifier(score: int) -> int:
    return math.floor((score - 10) / 2)


def _hp_average(hit_die_size: int) -> int:
    return (hit_die_size // 2) + 1


def _proficiency_bonus_for_level(level: int) -> int:
    return 2 + ((level - 1) // 4)


def _level_data(class_index: str, level: int) -> dict | None:
    levels = get_class_levels(class_index)
    if not levels or level < 1 or level > len(levels):
        return None
    return levels[level - 1]


def _is_asi_level(class_index: str, target_level: int) -> bool:
    """A level is an ASI level if ability_score_bonuses increased from prev level."""
    if target_level < 2:
        return False
    target = _level_data(class_index, target_level)
    prev = _level_data(class_index, target_level - 1)
    if target is None or prev is None:
        return False
    return target.get("ability_score_bonuses", 0) > prev.get("ability_score_bonuses", 0)


def _spell_slots_for_level(class_index: str, level: int) -> dict[str, int] | None:
    data = _level_data(class_index, level)
    if data is None:
        return None
    sc = data.get("spellcasting")
    if not sc:
        return None
    slots = {str(i): sc[f"spell_slots_level_{i}"] for i in range(1, 10) if sc.get(f"spell_slots_level_{i}", 0) > 0}
    return slots or None


def initialize_resources(class_index: str, level: int) -> dict[str, dict]:
    """Build the resources dict for a character at the given class+level."""
    data = _level_data(class_index, level)
    if data is None:
        return {}
    cs = data.get("class_specific") or {}
    resources: dict[str, dict] = {}
    for srd_key, (name, reset) in RESOURCE_MAP.items():
        value = cs.get(srd_key)
        if isinstance(value, int) and value > 0:
            resources[name] = {"current": value, "max": value, "resets_on": reset}
    return resources


def expected_spell_picks(class_index: str, target_level: int) -> int:
    """Total new spells + cantrips a character should pick on level-up."""
    target = _level_data(class_index, target_level)
    if target is None:
        return 0
    prev = _level_data(class_index, target_level - 1) if target_level >= 2 else None
    target_sc = target.get("spellcasting") or {}
    prev_sc = (prev or {}).get("spellcasting") or {}

    cantrips_delta = (target_sc.get("cantrips_known") or 0) - (prev_sc.get("cantrips_known") or 0)

    # Wizard: +2 spells per level into spellbook (not encoded in SRD spells_known).
    if class_index == "wizard" and target_level >= 2:
        spells_delta = 2
    elif target_sc.get("spells_known") is not None:
        spells_delta = (target_sc.get("spells_known") or 0) - (prev_sc.get("spells_known") or 0)
    else:
        # Prepared casters (cleric, druid, paladin) don't pick on level-up.
        spells_delta = 0

    return max(0, cantrips_delta) + max(0, spells_delta)


def recompute_derived_stats(char: Character) -> None:
    """Re-derive initiative, passive_perception, and AC from current state + feats."""
    feat_indices = {f["index"] for f in (char.feats or [])}

    dex_mod = _ability_modifier(char.ability_scores.get("dex", 10))
    char.initiative = dex_mod + (char.proficiency_bonus if "alert" in feat_indices else 0)

    wis_mod = _ability_modifier(char.ability_scores.get("wis", 10))
    has_perception = any(s.lower() == "perception" for s in (char.skill_proficiencies or []))
    char.passive_perception = 10 + wis_mod + (2 if has_perception else 0) + (5 if "observant" in feat_indices else 0)

    char.ac = derive_ac(AcInput.from_row(char))


# Preview


def build_level_up_preview(char: Character) -> dict | None:
    """Frontend-facing block describing exactly what the player must choose for the next level."""
    if not has_pending_level_up(char):
        return None
    target_level = char.level + 1
    cls = char.class_
    target_data = _level_data(cls, target_level)
    if target_data is None:
        return None

    asi_or_feat = _is_asi_level(cls, target_level)
    needs_subclass = SUBCLASS_LEVEL.get(cls) == target_level and not char.subclass

    available_subclasses: list[dict] = []
    if needs_subclass:
        available_subclasses = [{"index": s["index"], "name": s["name"]} for s in list_subclasses_for_class(cls)]

    available_feats: list[dict] = []
    if asi_or_feat:
        available_feats = [
            {"index": f["index"], "name": f["name"], "type": f.get("type", "general")}
            for f in list_all_feats()
            if f.get("type") in {"general", "epic-boon"} and f["index"] != "ability-score-improvement"
        ]

    return {
        "target_level": target_level,
        "hp": {
            "die": char.hit_die_size,
            "average": _hp_average(char.hit_die_size),
            "con_modifier": _ability_modifier(char.ability_scores.get("con", 10)),
        },
        "asi_or_feat": asi_or_feat,
        "subclass_required": needs_subclass,
        "available_subclasses": available_subclasses,
        "available_feats": available_feats,
        "new_features": [{"index": f["index"], "name": f["name"]} for f in target_data.get("features", [])],
        "new_spell_slots": _spell_slots_for_level(cls, target_level),
        "spells_to_choose": expected_spell_picks(cls, target_level),
        "proficiency_bonus": _proficiency_bonus_for_level(target_level),
    }


# Choices schema


@dataclass
class LevelUpChoices:
    hp_method: str  # "roll" or "average"
    hp_roll: int | None = None
    asi: dict[str, int] | None = None
    feat: str | None = None
    feat_options: dict | None = None
    new_spells: list[str] = field(default_factory=list)
    subclass: str | None = None


# Service entrypoints


async def get_level_up_preview(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    campaign_id: uuid.UUID,
    owner_id: str,
) -> dict:
    char = await character_queries.get_character_for_campaign_owned_by(db, character_id, campaign_id, owner_id)
    preview = build_level_up_preview(char)
    if preview is None:
        return {"pending": False}
    return {"pending": True, **preview}


async def _award_xp(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    amount: int,
) -> dict:
    """Award XP without an ownership check — for tool-facing use inside a trusted session."""
    if amount < 0:
        raise ValidationError(f"xp amount must be non-negative, got {amount}")
    char = await character_queries.get_character(db, character_id)
    char.xp = (char.xp or 0) + amount
    ready = has_pending_level_up(char)
    log.info(
        "xp_awarded",
        character_id=str(char.id),
        amount=amount,
        total_xp=char.xp,
        ready_to_level_up=ready,
    )
    return {"character": char.name, "xp": char.xp, "level": char.level, "ready_to_level_up": ready}


async def award_xp(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    campaign_id: uuid.UUID,
    owner_id: str,
    amount: int,
) -> dict:
    """Add XP to a character. Returns whether they're now ready to level up."""
    if amount < 0:
        raise ValidationError(f"xp amount must be non-negative, got {amount}")
    char = await character_queries.get_character_for_campaign_owned_by(db, character_id, campaign_id, owner_id)
    char.xp = (char.xp or 0) + amount
    ready = has_pending_level_up(char)
    log.info(
        "xp_awarded",
        character_id=str(char.id),
        amount=amount,
        total_xp=char.xp,
        ready_to_level_up=ready,
    )
    return {"xp": char.xp, "level": char.level, "ready_to_level_up": ready}


async def apply_level_up(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    campaign_id: uuid.UUID,
    owner_id: str,
    choices: LevelUpChoices,
) -> Character:
    char = await character_queries.get_character_for_campaign_owned_by(db, character_id, campaign_id, owner_id)

    if not has_pending_level_up(char):
        raise ValidationError(f"{char.name} has no pending level-up (xp={char.xp}, level={char.level})")

    # Block during active combat — UI/route enforces too, this is the safety net.
    active_session = await session_queries.get_active_session(db, char.campaign_id)
    if active_session is not None and active_session.combat_active:
        raise ConflictError("cannot level up during active combat", code="combat_active")

    target_level = char.level + 1
    cls = char.class_
    target_data = _level_data(cls, target_level)
    if target_data is None:
        raise ValidationError(f"max level reached for {cls}")

    _validate_choices_against_preview(char, choices, target_level)

    # 1. HP
    hp_gain = _resolve_hp_gain(char.hit_die_size, choices)
    con_mod = _ability_modifier(char.ability_scores.get("con", 10))
    char.max_hp = char.max_hp + hp_gain + con_mod
    char.hp = char.hp + hp_gain + con_mod

    # Tough feat: +2 max HP for every level gained after taking it
    if any(f["index"] == "tough" for f in (char.feats or [])):
        char.max_hp = char.max_hp + 2
        char.hp = char.hp + 2

    # 2. ASI / feat (if applicable)
    if _is_asi_level(cls, target_level):
        if choices.asi is not None:
            _apply_asi(char, choices.asi)
        elif choices.feat is not None:
            feat_effects.apply_feat(char, choices.feat, choices.feat_options)
        else:
            raise ValidationError("must choose asi or feat at this level")

    # 3. Subclass (if applicable)
    if SUBCLASS_LEVEL.get(cls) == target_level and not char.subclass:
        if choices.subclass is None:
            raise ValidationError("subclass choice required at this level")
        char.subclass = choices.subclass

    # 4. Spell slots — re-derive from class table for the new level
    new_slots = _spell_slots_for_level(cls, target_level)
    if new_slots is not None:
        char.spell_slots = new_slots

    # 5. New spells learned
    if choices.new_spells:
        char.spells_known = list(char.spells_known) + list(choices.new_spells)

    # 6. New features — append for visibility (LLM reads this list)
    new_features: list[FeatureEntry] = [
        {"index": f["index"], "name": f["name"]} for f in target_data.get("features", [])
    ]
    char.features = list(char.features) + new_features

    # 7. Bookkeeping: level, prof bonus, hit dice
    char.level = target_level
    char.proficiency_bonus = _proficiency_bonus_for_level(target_level)
    char.hit_dice_remaining = (char.hit_dice_remaining or 0) + 1

    # 8. Resources — re-derive max from new level, preserve current spent uses
    char.resources = _merge_resources(char.resources or {}, initialize_resources(cls, target_level))

    # 9. Re-derive initiative & passive_perception from final ability scores + feats
    recompute_derived_stats(char)

    log.info(
        "level_up_applied",
        character_id=str(char.id),
        new_level=target_level,
        class_=cls,
    )
    return char


# Internal mutators


def _resolve_hp_gain(hit_die_size: int, choices: LevelUpChoices) -> int:
    if choices.hp_method == "average":
        return _hp_average(hit_die_size)
    if choices.hp_method == "roll":
        if choices.hp_roll is None:
            raise ValidationError("hp_roll required when hp_method is 'roll'")
        if not 1 <= choices.hp_roll <= hit_die_size:
            raise ValidationError(f"hp_roll must be 1-{hit_die_size}, got {choices.hp_roll}")
        return choices.hp_roll
    raise ValidationError(f"hp_method must be 'roll' or 'average', got {choices.hp_method!r}")


def _apply_asi(char: Character, asi: dict[str, int]) -> None:
    bad_keys = set(asi) - _ABILITY_KEYS
    if bad_keys:
        raise ValidationError(f"invalid ability keys in asi: {sorted(bad_keys)}")
    if any(v not in (1, 2) for v in asi.values()):
        raise ValidationError("each asi increment must be 1 or 2")
    if sum(asi.values()) != 2:
        raise ValidationError(f"asi must total 2 points, got {sum(asi.values())}")

    new_scores: AbilityScores = {**char.ability_scores}
    for k, v in asi.items():
        new_score = get_ability_score(new_scores, k) + v
        if new_score > 20:
            raise ValidationError(f"{k} cannot exceed 20")
        new_scores[cast(AbilityKey, k)] = new_score
    char.ability_scores = new_scores


def _validate_choices_against_preview(char: Character, choices: LevelUpChoices, target_level: int) -> None:
    cls = char.class_
    asi_level = _is_asi_level(cls, target_level)

    if asi_level:
        asi_set = choices.asi is not None
        feat_set = choices.feat is not None
        if asi_set == feat_set:
            raise ValidationError("must choose exactly one of asi or feat at this level")
        if feat_set and choices.feat is not None:
            feat_data = get_feat(choices.feat)
            if feat_data is None:
                raise ValidationError(f"unknown feat: {choices.feat}")
            if feat_data.get("type") not in {"general", "epic-boon"}:
                raise ValidationError(
                    f"feat {choices.feat!r} (type={feat_data.get('type', 'general')}) "
                    f"is not available at ASI levels — only general and epic-boon feats"
                )
    else:
        if choices.asi is not None or choices.feat is not None:
            raise ValidationError(f"level {target_level} does not grant ASI/feat for {cls}")

    needs_subclass = SUBCLASS_LEVEL.get(cls) == target_level and not char.subclass
    if needs_subclass:
        if choices.subclass is None:
            raise ValidationError("subclass choice required at this level")
        sub = get_subclass(choices.subclass)
        if sub is None or sub.get("class", {}).get("index") != cls:
            raise ValidationError(f"invalid subclass for {cls}: {choices.subclass!r}")
    elif choices.subclass is not None:
        raise ValidationError("subclass not chosen at this level")

    expected = expected_spell_picks(cls, target_level)
    provided = len(choices.new_spells or [])
    if provided != expected:
        raise ValidationError(f"expected {expected} new spell(s)/cantrip(s) for {cls} L{target_level}, got {provided}")


def _merge_resources(existing: dict, fresh: dict) -> dict:
    """Re-derive max from the new level; preserve already-spent uses; grant deltas."""
    merged = dict(existing)
    for name, default_state in fresh.items():
        if name in merged:
            old = merged[name]
            old_max = old.get("max", 0)
            new_max = default_state["max"]
            if new_max > old_max:
                # Grant the new uses to current as well
                old["current"] = old.get("current", 0) + (new_max - old_max)
                old["max"] = new_max
            old["resets_on"] = default_state["resets_on"]
        else:
            merged[name] = default_state
    return merged
