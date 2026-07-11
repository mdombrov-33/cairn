import math
import random
import uuid
from typing import TypedDict, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.application import time as time_service
from cairn.db.models.character import Character
from cairn.db.models.session import Session
from cairn.db.queries import characters as character_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.combat_rules import exhaustion_level
from cairn.domain.exceptions import ConflictError, NotFoundError

log = structlog.get_logger()

# Classes whose spell lists require active daily preparation (long rest re-prep).
PREPARED_CASTERS = {"cleric", "druid", "paladin", "wizard"}


class CharacterRestResult(TypedDict):
    character_id: str
    name: str
    hp_restored: int
    hp_new: int
    resources_reset: list[str]
    spell_slots_restored: bool
    prepared_spells_cleared: bool


class HitDieResult(TypedDict):
    character_id: str
    die_size: int
    roll: int
    con_modifier: int
    hp_gained: int
    hp_new: int
    hit_dice_remaining: int


def _ability_modifier(score: int) -> int:
    return math.floor((score - 10) / 2)


def _can_rest(session: Session) -> tuple[bool, str]:
    if session.combat_active:
        return False, "in_combat"
    # TODO Slice 6: check scene.safety_level — hostile environment blocks rest, risky warns
    return True, ""


def _reset_character_short_rest(char: Character) -> CharacterRestResult:
    resources_reset: list[str] = []
    new_resources = dict(char.resources or {})
    for name, res in new_resources.items():
        if res.get("resets_on") == "short_rest":
            new_resources[name] = {**res, "current": res["max"]}
            resources_reset.append(name)
    char.resources = new_resources

    # Warlock spell slots recharge on short rest
    slots_restored = False
    if char.class_name == "warlock" and char.spell_slots:
        from cairn.srd import get_class_levels

        levels = get_class_levels("warlock")
        if char.level >= 1 and char.level <= len(levels):
            sc = levels[char.level - 1].get("spellcasting") or {}
            full_slots = {
                str(i): sc[f"spell_slots_level_{i}"] for i in range(1, 10) if sc.get(f"spell_slots_level_{i}", 0) > 0
            }
            if full_slots:
                char.spell_slots = full_slots
                slots_restored = True

    return CharacterRestResult(
        character_id=str(char.id),
        name=char.name,
        hp_restored=0,
        hp_new=char.hp,
        resources_reset=resources_reset,
        spell_slots_restored=slots_restored,
        prepared_spells_cleared=False,
    )


def _reset_character_long_rest(char: Character) -> CharacterRestResult:
    hp_before = char.hp
    char.hp = char.max_hp

    # All resources reset (long rest resets both short- and long-rest resources)
    resources_reset: list[str] = []
    new_resources = dict(char.resources or {})
    for name, res in new_resources.items():
        if res.get("resets_on") in ("short_rest", "long_rest"):
            new_resources[name] = {**res, "current": res["max"]}
            resources_reset.append(name)
    char.resources = new_resources

    # Full spell slots restored for all casters
    slots_restored = False
    if char.spell_slots is not None:
        from cairn.srd import get_class_levels

        levels = get_class_levels(char.class_name)
        if char.level >= 1 and char.level <= len(levels):
            sc = levels[char.level - 1].get("spellcasting") or {}
            full_slots = {
                str(i): sc[f"spell_slots_level_{i}"] for i in range(1, 10) if sc.get(f"spell_slots_level_{i}", 0) > 0
            }
            if full_slots:
                char.spell_slots = full_slots
                slots_restored = True

    # Restore half max hit dice (min 1)
    max_hd = char.level
    hd_restore = max(1, max_hd // 2)
    char.hit_dice_remaining = min(max_hd, (char.hit_dice_remaining or 0) + hd_restore)

    # Exhaustion -1 (stored as "exhaustion-N" in conditions)
    current_exhaustion = exhaustion_level(char.conditions or [])
    if current_exhaustion > 0:
        new_level = current_exhaustion - 1
        conditions = [c for c in (char.conditions or []) if not c.startswith("exhaustion-")]
        if new_level > 0:
            conditions.append(f"exhaustion-{new_level}")
        char.conditions = conditions

    # Clear prepared spells for prepared casters — player re-preps after long rest.
    # TODO Slice 10: companions with settings.companion.leveling == "ai" should auto-re-prepare
    # instead of entering the spell_prep_required flow; skip clearing and pick spells server-side.
    prepared_cleared = False
    if char.class_name in PREPARED_CASTERS:
        char.prepared_spells = []
        prepared_cleared = True

    return CharacterRestResult(
        character_id=str(char.id),
        name=char.name,
        hp_restored=char.hp - hp_before,
        hp_new=char.hp,
        resources_reset=resources_reset,
        spell_slots_restored=slots_restored,
        prepared_spells_cleared=prepared_cleared,
    )


async def apply_short_rest(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> dict:
    session = await session_queries.get_session(db, session_id)
    ok, reason = _can_rest(session)
    if not ok:
        raise ConflictError(f"cannot rest: {reason}", code=reason)

    party = await character_queries.get_party_for_session(db, session_id)
    if not party:
        raise NotFoundError("no party members in session", code="no_party")

    results = [_reset_character_short_rest(char) for char in party]

    await time_service.advance_time(db, session, hours=1, source="short_rest")  # short rest ~1 hour
    log.info("short_rest_applied", session_id=str(session_id), party_size=len(party))
    return {"rest_type": "short", "results": results}


async def apply_long_rest(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> dict:
    session = await session_queries.get_session(db, session_id)
    ok, reason = _can_rest(session)
    if not ok:
        raise ConflictError(f"cannot rest: {reason}", code=reason)

    party = await character_queries.get_party_for_session(db, session_id)
    if not party:
        raise NotFoundError("no party members in session", code="no_party")

    results = [_reset_character_long_rest(char) for char in party]

    await time_service.advance_time(db, session, hours=8, source="long_rest")  # long rest = 8 hours
    log.info("long_rest_applied", session_id=str(session_id), party_size=len(party))

    needs_spell_prep = [r["character_id"] for r in results if r["prepared_spells_cleared"]]
    return {"rest_type": "long", "results": results, "spell_prep_required": needs_spell_prep}


async def roll_hit_die(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
) -> HitDieResult:
    char = await character_queries.get_character(db, character_id)
    if (char.hit_dice_remaining or 0) <= 0:
        raise ConflictError("no hit dice remaining", code="no_hit_dice")

    roll = random.randint(1, char.hit_die_size)
    con_mod = _ability_modifier(char.ability_scores.get("con", 10))
    hp_before = char.hp
    hp_gained = max(1, roll + con_mod)
    char.hp = min(char.max_hp, char.hp + hp_gained)
    char.hit_dice_remaining = (char.hit_dice_remaining or 1) - 1

    return HitDieResult(
        character_id=str(char.id),
        die_size=char.hit_die_size,
        roll=roll,
        con_modifier=con_mod,
        hp_gained=char.hp - hp_before,
        hp_new=char.hp,
        hit_dice_remaining=char.hit_dice_remaining,
    )


async def prepare_spells(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    campaign_id: uuid.UUID,
    owner_id: str,
    spells: list[str],
) -> Character:
    from cairn.domain.exceptions import ValidationError

    char = await character_queries.get_character_for_campaign_owned_by(db, character_id, campaign_id, owner_id)

    if char.class_name not in PREPARED_CASTERS:
        raise ValidationError(f"{char.class_name} does not prepare spells")

    # Validate all spells are in spells_known (or class list for clerics/druids/paladins)
    # For now validate count only — full legality check requires SRD class spell list lookup
    # TODO Slice 5: validate each spell is on the class spell list
    max_prepared = _max_prepared_spells(char)
    if len(spells) > max_prepared:
        raise ValidationError(f"may prepare at most {max_prepared} spells, got {len(spells)}")

    char.prepared_spells = list(spells)
    log.info("spells_prepared", character_id=str(char.id), count=len(spells))
    return char


def build_rest_context(rest_type: str, result: dict) -> str:
    hours = "1 hour" if rest_type == "short" else "8 hours"
    label = "Short" if rest_type == "short" else "Long"
    lines = [f"[{label} Rest — {hours}]"]
    for r in result.get("results", []):
        parts: list[str] = [r["name"]]
        if r["hp_restored"] > 0:
            parts.append(f"HP +{r['hp_restored']} (now {r['hp_new']})")
        if r["resources_reset"]:
            parts.append(f"restored: {', '.join(r['resources_reset'])}")
        if r["spell_slots_restored"]:
            parts.append("spell slots restored")
        if r["prepared_spells_cleared"]:
            parts.append("must re-prepare spells")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


def build_blocked_context(reason: str) -> str:
    detail = {
        "in_combat": "The party is engaged in combat.",
    }.get(reason, f"Rest is not possible right now ({reason}).")
    return f"[Rest Blocked — {reason}]\n{detail}"


def _max_prepared_spells(char: Character) -> int:
    """Prepared spell cap per class (ability mod + level, minimum 1)."""
    scores = cast(dict[str, int], char.ability_scores)
    if char.class_name == "paladin":
        mod = _ability_modifier(scores.get("cha", 10))
        return max(1, mod + char.level // 2)
    ability_key = {"wizard": "int", "cleric": "wis", "druid": "wis"}.get(char.class_name, "int")
    mod = _ability_modifier(scores.get(ability_key, 10))
    return max(1, mod + char.level)
