import uuid

import structlog
from langchain_core.tools import tool

from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import sessions as session_queries

log = structlog.get_logger()


@tool
async def consume_spell_slot(character_id: str, level: int) -> dict:
    """Consume one spell slot of the given level from a character.

    Call this whenever a character casts a leveled spell (not cantrips).
    Returns error if no slots remain at that level.

    Args:
        character_id: The character's UUID.
        level: Spell slot level to consume (1-9).
    """
    async with db_client.get_session() as db:
        try:
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
        except Exception as exc:
            log.error("tool_error", tool="consume_spell_slot", error=str(exc))
            return {"error": str(exc)}


@tool
async def restore_spell_slot(character_id: str, level: int, count: int = 1) -> dict:
    """Restore spell slots of the given level (e.g. Arcane Recovery, short rest for Warlock).

    Args:
        character_id: The character's UUID.
        level: Spell slot level to restore (1-9).
        count: Number of slots to restore. Default 1.
    """
    async with db_client.get_session() as db:
        try:
            char = await character_queries.get_character(db, uuid.UUID(character_id))
            slots = dict(char.spell_slots or {})
            key = str(level)
            slot = slots.get(key, {"current": 0, "max": 0})
            slot["current"] = min(slot.get("max", 0), slot.get("current", 0) + count)
            slots[key] = slot
            char.spell_slots = slots
            await db.commit()
            return {"character": char.name, "level": level, "slots_remaining": slot["current"]}
        except Exception as exc:
            log.error("tool_error", tool="restore_spell_slot", error=str(exc))
            return {"error": str(exc)}


@tool
async def use_resource(character_id: str, resource: str, count: int = 1) -> dict:
    """Spend uses of a class resource (Action Surge, Ki, Rage, Superiority Dice, Second Wind, etc.).

    Resources are tracked as {"current": N, "max": N, "resets_on": "short_rest"|"long_rest"}.
    Returns error if insufficient uses remain.

    Args:
        character_id: The character's UUID.
        resource: Resource key, e.g. "action_surge", "ki", "rage", "superiority_dice", "second_wind",
                  "channel_divinity", "bardic_inspiration", "wild_shape", "lay_on_hands".
        count: Number of uses to spend. Default 1.
    """  # noqa: E501
    async with db_client.get_session() as db:
        try:
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
        except Exception as exc:
            log.error("tool_error", tool="use_resource", error=str(exc))
            return {"error": str(exc)}


@tool
async def restore_resource(character_id: str, resource: str, count: int = 1) -> dict:
    """Restore uses of a class resource (e.g. after a short or long rest, or from a feature).

    Args:
        character_id: The character's UUID.
        resource: Resource key to restore.
        count: Number of uses to restore. Default 1.
    """
    async with db_client.get_session() as db:
        try:
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
        except Exception as exc:
            log.error("tool_error", tool="restore_resource", error=str(exc))
            return {"error": str(exc)}


@tool
async def set_concentration(character_id: str, spell_name: str) -> dict:
    """Begin concentrating on a spell. Automatically drops any previous concentration.

    Call this after successfully casting a concentration spell.

    Args:
        character_id: The character's UUID.
        spell_name: Name of the spell being concentrated on, e.g. "Bless", "Haste", "Hold Person".
    """
    async with db_client.get_session() as db:
        try:
            char = await character_queries.get_character(db, uuid.UUID(character_id))
            previous = char.concentration
            char.concentration = spell_name
            await db.commit()
            result: dict = {"character": char.name, "concentrating_on": spell_name}
            if previous:
                result["dropped"] = previous
            return result
        except Exception as exc:
            log.error("tool_error", tool="set_concentration", error=str(exc))
            return {"error": str(exc)}


@tool
async def drop_concentration(character_id: str) -> dict:
    """End a character's concentration, dismissing its active spell.

    Call this when: the character chooses to drop concentration, they fail a
    concentration saving throw, they cast another concentration spell, or they die.

    Args:
        character_id: The character's UUID.
    """
    async with db_client.get_session() as db:
        try:
            char = await character_queries.get_character(db, uuid.UUID(character_id))
            spell = char.concentration
            if not spell:
                return {"character": char.name, "note": "Not concentrating on anything."}
            char.concentration = None
            await db.commit()
            return {"character": char.name, "dropped_concentration": spell}
        except Exception as exc:
            log.error("tool_error", tool="drop_concentration", error=str(exc))
            return {"error": str(exc)}


@tool
async def roll_concentration_check(character_id: str, damage_taken: int) -> dict:
    """Roll a Constitution saving throw to maintain concentration after taking damage.

    DC = max(10, half the damage taken). Uses character's CON modifier + proficiency
    if they have the War Caster or Resilience (CON) feat.

    Call this immediately after a concentrating character takes damage.

    Args:
        character_id: The character's UUID.
        damage_taken: Total damage taken that triggered the check.
    """
    import math
    import random

    async with db_client.get_session() as db:
        try:
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
        except Exception as exc:
            log.error("tool_error", tool="roll_concentration_check", error=str(exc))
            return {"error": str(exc)}


@tool
async def use_action(session_id: str, combatant_id: str) -> dict:
    """Mark a combatant's action as used for this turn.

    Call this when a character takes their main action (Attack, Cast a Spell, Dash, etc.).
    Returns error if action already used this turn.

    Args:
        session_id: The session UUID.
        combatant_id: The combatant's UUID.
    """
    return await _spend_economy(session_id, combatant_id, "action_used")


@tool
async def use_bonus_action(session_id: str, combatant_id: str) -> dict:
    """Mark a combatant's bonus action as used for this turn.

    Call this when a character uses their bonus action (Off-hand Attack, Misty Step, Healing Word, etc.).
    Returns error if bonus action already used this turn.

    Args:
        session_id: The session UUID.
        combatant_id: The combatant's UUID.
    """  # noqa: E501
    return await _spend_economy(session_id, combatant_id, "bonus_action_used")


@tool
async def use_reaction(session_id: str, combatant_id: str) -> dict:
    """Mark a combatant's reaction as used until the start of their next turn.

    Call this for Opportunity Attacks, Shield, Counterspell, Hellish Rebuke, etc.
    Returns error if reaction already used this round.

    Args:
        session_id: The session UUID.
        combatant_id: The combatant's UUID.
    """
    return await _spend_economy(session_id, combatant_id, "reaction_used")


@tool
async def spend_movement(session_id: str, combatant_id: str, feet: int) -> dict:
    """Spend movement for a combatant this turn.

    Returns error if insufficient movement remains.

    Args:
        session_id: The session UUID.
        combatant_id: The combatant's UUID.
        feet: Amount of movement to spend.
    """
    async with db_client.get_session() as db:
        try:
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
        except Exception as exc:
            log.error("tool_error", tool="spend_movement", error=str(exc))
            return {"error": str(exc)}


async def _spend_economy(session_id: str, combatant_id: str, field: str) -> dict:
    async with db_client.get_session() as db:
        try:
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
        except Exception as exc:
            log.error("tool_error", tool=field, error=str(exc))
            return {"error": str(exc)}
