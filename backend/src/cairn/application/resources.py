import copy
import math
import random
import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.queries import characters as character_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.combat import CombatState, TurnEconomy
from cairn.domain.combat_rules import empty_combat_state


async def consume_spell_slot(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    level: int,
    count: int = 1,
) -> dict:
    char = await character_queries.get_character(db, character_id)
    slots = dict(char.spell_slots or {})
    key = str(level)
    remaining = slots.get(key, 0)
    if remaining < count:
        return {"error": f"{char.name} has no level {level} spell slots remaining."}
    slots[key] = remaining - count
    char.spell_slots = slots
    await db.commit()
    return {
        "character": char.name,
        "level": level,
        "slots_remaining": slots[key],
    }


async def restore_spell_slot(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    level: int,
    count: int = 1,
) -> dict:
    char = await character_queries.get_character(db, character_id)
    slots = dict(char.spell_slots or {})
    key = str(level)
    slots[key] = slots.get(key, 0) + count
    char.spell_slots = slots
    await db.commit()
    return {"character": char.name, "level": level, "slots_remaining": slots[key]}


async def use_resource(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    resource: str,
    count: int = 1,
) -> dict:
    char = await character_queries.get_character(db, character_id)
    resources = copy.deepcopy(char.resources or {})
    r = resources.get(resource)
    if r is None:
        return {"error": f"{char.name} does not have the resource '{resource}'."}
    current = r.get("current", 0)
    if current < count:
        return {"error": f"{char.name} has only {current} use(s) of {resource} remaining."}
    r["current"] = current - count
    resources[resource] = r
    char.resources = resources
    await db.commit()
    return {
        "character": char.name,
        "resource": resource,
        "uses_remaining": r["current"],
        "uses_max": r.get("max", 0),
    }


async def restore_resource(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    resource: str,
    count: int = 1,
) -> dict:
    char = await character_queries.get_character(db, character_id)
    resources = copy.deepcopy(char.resources or {})
    r = resources.get(resource)
    if r is None:
        return {"error": f"{char.name} does not have the resource '{resource}'."}
    r["current"] = min(r.get("max", 0), r.get("current", 0) + count)
    resources[resource] = r
    char.resources = resources
    await db.commit()
    return {"character": char.name, "resource": resource, "uses_remaining": r["current"]}


async def set_concentration(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    spell_name: str,
    level: int = 1,
    source_effect_id: str | None = None,
) -> dict:
    char = await character_queries.get_character(db, character_id)
    previous = char.concentration
    char.concentration = {"spell_name": spell_name, "level": level, "source_effect_id": source_effect_id}
    await db.commit()
    result: dict = {"character": char.name, "concentrating_on": spell_name, "level": level}
    if previous:
        result["dropped"] = previous.get("spell_name")
    return result


async def drop_concentration(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
) -> dict:
    char = await character_queries.get_character(db, character_id)
    record = char.concentration
    if not record:
        return {"character": char.name, "note": "Not concentrating on anything.", "dropped": None}
    char.concentration = None
    await db.commit()
    return {
        "character": char.name,
        "dropped_concentration": record.get("spell_name"),
        "dropped": dict(record),
    }


async def roll_concentration_check(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    damage_taken: int,
) -> dict:
    char = await character_queries.get_character(db, character_id)
    if not char.concentration:
        return {"character": char.name, "note": "Not concentrating — no check needed."}
    spell = char.concentration.get("spell_name")
    dc = max(10, math.floor(damage_taken / 2))
    con = char.ability_scores.get("con", 10)
    con_mod = math.floor((con - 10) / 2)
    roll = random.randint(1, 20)
    total = roll + con_mod
    success = total >= dc
    if not success:
        char.concentration = None
    await db.commit()
    return {
        "character": char.name,
        "spell": spell if success else None,
        "dc": dc,
        "roll": roll,
        "con_modifier": con_mod,
        "total": total,
        "success": success,
        "concentration_maintained": success,
        "concentration_lost": not success,
    }


EconomyFlag = Literal["action_used", "bonus_action_used", "reaction_used"]


def _movement_speed(state: CombatState, combatant_id: str) -> int:
    combatant = next((item for item in state["combatants"] if item["id"] == combatant_id), None)
    return combatant["speed"] if combatant is not None else 0


async def spend_economy(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    field: EconomyFlag,
) -> dict:
    session = await session_queries.get_session(db, session_id)
    state = session.combat_state or empty_combat_state()
    economy = state.setdefault("turn_economy", {})
    entry: TurnEconomy = economy.setdefault(
        combatant_id,
        {
            "action_used": False,
            "bonus_action_used": False,
            "reaction_used": False,
            "movement_remaining": _movement_speed(state, combatant_id),
        },
    )
    if entry[field]:
        label = field.replace("_used", "").replace("_", " ")
        return {"error": f"{label} already used this turn."}
    entry[field] = True
    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=session.combat_active)
    await db.commit()
    return {"combatant_id": combatant_id, field: True}


async def spend_movement(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    feet: int,
) -> dict:
    session = await session_queries.get_session(db, session_id)
    state = session.combat_state or empty_combat_state()
    economy = state.setdefault("turn_economy", {})
    entry = economy.setdefault(
        combatant_id,
        {
            "action_used": False,
            "bonus_action_used": False,
            "reaction_used": False,
            "movement_remaining": _movement_speed(state, combatant_id),
        },
    )
    remaining = entry.get("movement_remaining", 0)
    if feet > remaining:
        return {"error": f"Only {remaining}ft of movement remaining this turn."}
    entry["movement_remaining"] = remaining - feet
    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=session.combat_active)
    await db.commit()
    return {
        "combatant_id": combatant_id,
        "movement_spent": feet,
        "movement_remaining": entry["movement_remaining"],
    }
