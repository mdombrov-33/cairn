import math
import random
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.agents import scene_narrator
from cairn.application import time as time_service
from cairn.db.models.character import Character
from cairn.db.models.session import Session
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.combat_rules import exhaustion_level
from cairn.domain.exceptions import ConflictError, NotFoundError
from cairn.domain.services.settings import resolve_settings
from cairn.srd.catalog import catalog
from cairn.srd.models import SpellRecord

log = structlog.get_logger()

# Classes whose spell lists require active daily preparation (long rest re-prep).
PREPARED_CASTERS = {"cleric", "druid", "paladin", "wizard"}
type RestType = Literal["short", "long"]


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


class RestStreamEvent(TypedDict):
    type: Literal["rest_applied", "rest_blocked", "rest_confirmation_required", "token", "rest_end"]
    data: dict[str, Any]


@dataclass(frozen=True)
class PreparedRest:
    """A validated rest outcome ready for transport-neutral narration."""

    rest_type: RestType
    event_type: Literal["rest_applied", "rest_blocked", "rest_confirmation_required"]
    event_data: dict[str, Any]
    context: str


def _ability_modifier(score: int) -> int:
    return math.floor((score - 10) / 2)


async def _rest_block_reason(db: AsyncSession, session: Session, *, confirm_risky: bool) -> str | None:
    if session.combat_active:
        return "in_combat"

    scene = await scene_queries.get_current_scene(db, session.campaign_id)
    if scene is None or scene.safety_level == "safe":
        return None
    if scene.safety_level == "hostile":
        return "hostile_scene"
    if scene.safety_level == "risky" and not confirm_risky:
        return "risky_scene"
    return None


def _spell_slots_at_current_level(char: Character) -> dict[str, int] | None:
    levels = catalog.class_levels(char.class_name)
    if not 1 <= char.level <= len(levels):
        return None
    return levels[char.level - 1].spell_slots()


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
        full_slots = _spell_slots_at_current_level(char)
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


def _reset_character_long_rest(char: Character, *, auto_prepare: bool) -> CharacterRestResult:
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
        full_slots = _spell_slots_at_current_level(char)
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

    # Player-controlled prepared casters choose a new list after resting. AI-controlled
    # companions retain legal spells first, then fill the remaining choices deterministically.
    prepared_cleared = False
    if char.class_name in PREPARED_CASTERS:
        if auto_prepare:
            char.prepared_spells = _default_prepared_spells(char)
        else:
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
    confirm_risky: bool = False,
) -> dict:
    session = await session_queries.get_session(db, session_id)
    reason = await _rest_block_reason(db, session, confirm_risky=confirm_risky)
    if reason is not None:
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
    confirm_risky: bool = False,
) -> dict:
    session = await session_queries.get_session(db, session_id)
    reason = await _rest_block_reason(db, session, confirm_risky=confirm_risky)
    if reason is not None:
        raise ConflictError(f"cannot rest: {reason}", code=reason)

    campaign = await campaign_queries.get_campaign(db, session.campaign_id)
    settings = resolve_settings(campaign.settings)

    party = await character_queries.get_party_for_session(db, session_id)
    if not party:
        raise NotFoundError("no party members in session", code="no_party")

    results = [
        _reset_character_long_rest(
            char,
            auto_prepare=char.is_companion and settings.companion.leveling == "ai",
        )
        for char in party
    ]

    await time_service.advance_time(db, session, hours=8, source="long_rest")  # long rest = 8 hours
    log.info("long_rest_applied", session_id=str(session_id), party_size=len(party))

    needs_spell_prep = [r["character_id"] for r in results if r["prepared_spells_cleared"]]
    return {"rest_type": "long", "results": results, "spell_prep_required": needs_spell_prep}


async def prepare_rest(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
    rest_type: RestType,
    confirm_risky: bool = False,
) -> PreparedRest:
    """Authorize and apply one rest, leaving the route only SSE formatting work."""

    session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, session.campaign_id, owner_id)

    try:
        result = (
            await apply_long_rest(db, session_id=session_id, confirm_risky=confirm_risky)
            if rest_type == "long"
            else await apply_short_rest(db, session_id=session_id, confirm_risky=confirm_risky)
        )
    except ConflictError as error:
        if error.code == "risky_scene":
            return PreparedRest(
                rest_type=rest_type,
                event_type="rest_confirmation_required",
                event_data={
                    "rest_type": rest_type,
                    "reason": error.code,
                    "message": "This scene is risky. Are you sure you want to rest? You might be ambushed.",
                },
                context=build_confirmation_context(rest_type),
            )
        return PreparedRest(
            rest_type=rest_type,
            event_type="rest_blocked",
            event_data={"reason": error.code},
            context=build_blocked_context(error.code),
        )

    return PreparedRest(
        rest_type=rest_type,
        event_type="rest_applied",
        event_data={"rest_type": rest_type, **result},
        context=build_rest_context(rest_type, result),
    )


async def stream(prepared: PreparedRest) -> AsyncGenerator[RestStreamEvent]:
    """Narrate a prepared rest as semantic events; SSE encoding belongs to the route."""

    yield {"type": prepared.event_type, "data": prepared.event_data}
    async for chunk in scene_narrator.run(f"{prepared.rest_type} rest", context=prepared.context):
        yield {"type": "token", "data": {"text": chunk}}
    yield {"type": "rest_end", "data": {}}


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

    max_prepared = _max_prepared_spells(char)
    if len(spells) > max_prepared:
        raise ValidationError(f"may prepare at most {max_prepared} spells, got {len(spells)}")
    if len({spell.casefold() for spell in spells}) != len(spells):
        raise ValidationError("prepared spells cannot contain duplicates")

    legal_spell_names = {spell.name.casefold() for spell in _legal_prepared_spells(char)}
    for spell_name in spells:
        record = catalog.spell(spell_name)
        if record is None or record.name.casefold() not in legal_spell_names:
            raise ValidationError(f"{spell_name} cannot be prepared by this character")

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
        "hostile_scene": "The current scene is too hostile for the party to rest.",
    }.get(reason, f"Rest is not possible right now ({reason}).")
    return f"[Rest Blocked — {reason}]\n{detail}"


def build_confirmation_context(rest_type: RestType) -> str:
    label = "Short" if rest_type == "short" else "Long"
    return (
        f"[{label} Rest — Confirmation Required]\n"
        "This scene is risky. Ask whether the party is sure they want to rest and warn that they might be ambushed."
    )


def _max_prepared_spells(char: Character) -> int:
    """Prepared spell cap per class (ability mod + level, minimum 1)."""
    scores = cast(dict[str, int], char.ability_scores)
    if char.class_name == "paladin":
        mod = _ability_modifier(scores.get("cha", 10))
        return max(1, mod + char.level // 2)
    ability_key = {"wizard": "int", "cleric": "wis", "druid": "wis"}.get(char.class_name, "int")
    mod = _ability_modifier(scores.get(ability_key, 10))
    return max(1, mod + char.level)


def _legal_prepared_spells(char: Character) -> tuple[SpellRecord, ...]:
    """Return the leveled spells this character may prepare at the current level."""

    slots = _spell_slots_at_current_level(char)
    max_spell_level = max((int(level) for level in slots or {}), default=0)
    if max_spell_level == 0:
        return ()

    if char.class_name == "wizard":
        known_spells = {spell.casefold() for spell in char.spells_known}
        return tuple(
            spell
            for spell in catalog.spells
            if 0 < spell.level <= max_spell_level and spell.name.casefold() in known_spells
        )

    return tuple(
        spell
        for spell in catalog.spells
        if 0 < spell.level <= max_spell_level
        and any(spell_class.index == char.class_name for spell_class in spell.classes)
    )


def _default_prepared_spells(char: Character) -> list[str]:
    """Choose stable legal preparations for an AI-controlled companion without an LLM call."""

    legal = _legal_prepared_spells(char)
    max_prepared = _max_prepared_spells(char)
    legal_by_name = {spell.name.casefold(): spell for spell in legal}
    selected: list[str] = []
    selected_names: set[str] = set()

    for spell_name in char.prepared_spells:
        if len(selected) >= max_prepared:
            break
        record = legal_by_name.get(spell_name.casefold())
        if record is not None and record.name.casefold() not in selected_names:
            selected.append(record.name)
            selected_names.add(record.name.casefold())

    for spell in legal:
        if len(selected) >= max_prepared:
            break
        if spell.name.casefold() not in selected_names:
            selected.append(spell.name)
            selected_names.add(spell.name.casefold())

    return selected
