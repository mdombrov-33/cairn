import math
import random
import uuid

from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import sessions as session_queries
from cairn.mcp.tools.base import prop, tool


async def _spend_economy(session_id: str, combatant_id: str, field: str) -> dict:
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        state = session.combat_state or {}
        economy = state.setdefault("turn_economy", {})
        entry = economy.setdefault(
            combatant_id,
            {
                "action_used": False,
                "bonus_action_used": False,
                "reaction_used": False,
                "movement_remaining": 30,
            },
        )
        if entry.get(field):
            label = field.replace("_used", "").replace("_", " ")
            return {"error": f"{label} already used this turn."}
        entry[field] = True
        await session_queries.update_combat_state(
            db, uuid.UUID(session_id), combat_state=state, combat_active=session.combat_active
        )
        await db.commit()
        return {"combatant_id": combatant_id, field: True}


@tool(
    "Consume one spell slot of the given level. Call whenever a character casts a leveled spell (not cantrips).",  # noqa: E501
    {
        "character_id": prop("string", "The character's UUID."),
        "level": prop("integer", "Spell slot level to consume (1-9)."),
    },
    required=["character_id", "level"],
)
async def consume_spell_slot(character_id: str, level: int) -> dict:
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(character_id))
        slots = dict(char.spell_slots or {})
        key = str(level)
        slot = slots.get(key, {})
        current = slot.get("current", 0)
        if current <= 0:
            return {"error": f"{char.name} has no level {level} spell slots remaining."}
        slot["current"] = current - 1
        slots[key] = slot
        char.spell_slots = slots
        await db.commit()
        return {
            "character": char.name,
            "level": level,
            "slots_remaining": slot["current"],
            "slots_max": slot.get("max", slot.get("current", 0)),
        }


@tool(
    "Restore spell slots of the given level (e.g. Arcane Recovery, short rest for Warlock).",
    {
        "character_id": prop("string", "The character's UUID."),
        "level": prop("integer", "Spell slot level to restore (1-9)."),
        "count": prop("integer", "Number of slots to restore. Default 1.", default=1),
    },
    required=["character_id", "level"],
)
async def restore_spell_slot(character_id: str, level: int, count: int = 1) -> dict:
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(character_id))
        slots = dict(char.spell_slots or {})
        key = str(level)
        slot = slots.get(key, {"current": 0, "max": 0})
        slot["current"] = min(slot.get("max", 0), slot.get("current", 0) + count)
        slots[key] = slot
        char.spell_slots = slots
        await db.commit()
        return {"character": char.name, "level": level, "slots_remaining": slot["current"]}


@tool(
    "Spend uses of a class resource (Action Surge, Ki, Rage, Superiority Dice, Second Wind, etc.).",
    {
        "character_id": prop("string", "The character's UUID."),
        "resource": prop(
            "string", 'Resource key, e.g. "action_surge", "ki", "rage", "bardic_inspiration".'
        ),
        "count": prop("integer", "Number of uses to spend. Default 1.", default=1),
    },
    required=["character_id", "resource"],
)
async def use_resource(character_id: str, resource: str, count: int = 1) -> dict:
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(character_id))
        resources = dict(char.resources or {})
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


@tool(
    "Restore uses of a class resource (e.g. after a short or long rest, or from a feature).",
    {
        "character_id": prop("string", "The character's UUID."),
        "resource": prop("string", "Resource key to restore."),
        "count": prop("integer", "Number of uses to restore. Default 1.", default=1),
    },
    required=["character_id", "resource"],
)
async def restore_resource(character_id: str, resource: str, count: int = 1) -> dict:
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(character_id))
        resources = dict(char.resources or {})
        r = resources.get(resource)
        if r is None:
            return {"error": f"{char.name} does not have the resource '{resource}'."}
        r["current"] = min(r.get("max", 0), r.get("current", 0) + count)
        resources[resource] = r
        char.resources = resources
        await db.commit()
        return {"character": char.name, "resource": resource, "uses_remaining": r["current"]}


@tool(
    "Begin concentrating on a spell. Automatically drops any previous concentration.",
    {
        "character_id": prop("string", "The character's UUID."),
        "spell_name": prop("string", 'Name of the spell, e.g. "Bless", "Haste", "Hold Person".'),
    },
    required=["character_id", "spell_name"],
)
async def set_concentration(character_id: str, spell_name: str) -> dict:
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(character_id))
        previous = char.concentration
        char.concentration = spell_name
        await db.commit()
        result: dict = {"character": char.name, "concentrating_on": spell_name}
        if previous:
            result["dropped"] = previous
        return result


@tool(
    "End a character's concentration. Call when they choose to drop it, fail a save, cast another concentration spell, or die.",  # noqa: E501
    {"character_id": prop("string", "The character's UUID.")},
    required=["character_id"],
)
async def drop_concentration(character_id: str) -> dict:
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(character_id))
        spell = char.concentration
        if not spell:
            return {"character": char.name, "note": "Not concentrating on anything."}
        char.concentration = None
        await db.commit()
        return {"character": char.name, "dropped_concentration": spell}


@tool(
    "Roll a Constitution saving throw to maintain concentration after taking damage. DC = max(10, half damage taken).",  # noqa: E501
    {
        "character_id": prop("string", "The character's UUID."),
        "damage_taken": prop("integer", "Total damage taken that triggered the check."),
    },
    required=["character_id", "damage_taken"],
)
async def roll_concentration_check(character_id: str, damage_taken: int) -> dict:
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(character_id))
        if not char.concentration:
            return {"character": char.name, "note": "Not concentrating — no check needed."}
        dc = max(10, math.floor(damage_taken / 2))
        con = char.stats.get("con", 10)
        con_mod = math.floor((con - 10) / 2)
        roll = random.randint(1, 20)
        total = roll + con_mod
        success = total >= dc
        if not success:
            char.concentration = None
        await db.commit()
        return {
            "character": char.name,
            "spell": char.concentration if success else None,
            "dc": dc,
            "roll": roll,
            "con_modifier": con_mod,
            "total": total,
            "success": success,
            "concentration_maintained": success,
            "concentration_lost": not success,
        }


@tool(
    "Mark a combatant's action as used for this turn (Attack, Cast a Spell, Dash, etc.).",
    {
        "session_id": prop("string", "The session UUID."),
        "combatant_id": prop("string", "The combatant's UUID."),
    },
    required=["session_id", "combatant_id"],
)
async def use_action(session_id: str, combatant_id: str) -> dict:
    return await _spend_economy(session_id, combatant_id, "action_used")


@tool(
    "Mark a combatant's bonus action as used for this turn (Off-hand Attack, Misty Step, Healing Word, etc.).",  # noqa: E501
    {
        "session_id": prop("string", "The session UUID."),
        "combatant_id": prop("string", "The combatant's UUID."),
    },
    required=["session_id", "combatant_id"],
)
async def use_bonus_action(session_id: str, combatant_id: str) -> dict:
    return await _spend_economy(session_id, combatant_id, "bonus_action_used")


@tool(
    "Mark a combatant's reaction as used until the start of their next turn (Opportunity Attack, Shield, Counterspell, etc.).",  # noqa: E501
    {
        "session_id": prop("string", "The session UUID."),
        "combatant_id": prop("string", "The combatant's UUID."),
    },
    required=["session_id", "combatant_id"],
)
async def use_reaction(session_id: str, combatant_id: str) -> dict:
    return await _spend_economy(session_id, combatant_id, "reaction_used")


@tool(
    "Spend movement for a combatant this turn.",
    {
        "session_id": prop("string", "The session UUID."),
        "combatant_id": prop("string", "The combatant's UUID."),
        "feet": prop("integer", "Amount of movement to spend."),
    },
    required=["session_id", "combatant_id", "feet"],
)
async def spend_movement(session_id: str, combatant_id: str, feet: int) -> dict:
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        state = session.combat_state or {}
        economy = state.setdefault("turn_economy", {})
        entry = economy.setdefault(
            combatant_id,
            {
                "action_used": False,
                "bonus_action_used": False,
                "reaction_used": False,
                "movement_remaining": 30,
            },
        )
        remaining = entry.get("movement_remaining", 0)
        if feet > remaining:
            return {"error": f"Only {remaining}ft of movement remaining this turn."}
        entry["movement_remaining"] = remaining - feet
        await session_queries.update_combat_state(
            db, uuid.UUID(session_id), combat_state=state, combat_active=session.combat_active
        )
        await db.commit()
        return {
            "combatant_id": combatant_id,
            "movement_spent": feet,
            "movement_remaining": entry["movement_remaining"],
        }
