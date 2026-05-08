import json
import uuid
from typing import Annotated

from langchain_core.tools import tool

import cairn.domain.services.combat as combat_service
from cairn.db import client as db_client
from cairn.db.queries import sessions as session_queries


@tool
async def start_combat(
    session_id: Annotated[str, "The session UUID."],
    enemies_json: Annotated[
        str,
        'JSON array of enemies. Each entry: {"type": "monster", "name": "goblin", "count": 2} or {"type": "npc", "id": "<uuid>", "team": "enemies"}.',  # noqa: E501
    ],
) -> dict:
    """Initialize a combat encounter. Rolls initiative for all combatants. Party members enrolled automatically. enemies_json is a JSON array of enemy descriptors."""  # noqa: E501
    try:
        enemies = json.loads(enemies_json)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid enemies_json: {e}"}

    async with db_client.get_session() as db:
        combat_state = await combat_service._init_state(db, uuid.UUID(session_id), enemies)
    return {"combat_started": True, "combat_state": combat_state}


@tool
async def end_combat(
    session_id: Annotated[str, "The session UUID."],
    outcome: Annotated[str, '"victory", "defeat", "retreat", or "resolved" (peaceful end).'],
) -> dict:
    """End the current combat encounter and clear combat state."""

    async with db_client.get_session() as db:
        await session_queries.update_combat_state(
            db, uuid.UUID(session_id), combat_state=None, combat_active=False
        )
        await db.commit()
    return {"combat_ended": True, "outcome": outcome}


@tool
async def apply_damage(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[
        str, "The combatant's ID (UUID for character/npc, generated id for monster)."
    ],
    combatant_type: Annotated[str, '"character", "npc", or "monster".'],
    amount: Annotated[int, "Raw damage amount before temp HP absorption."],
    damage_type: Annotated[
        str, 'Damage type for narrative purposes, e.g. "fire", "slashing".'
    ] = "untyped",
) -> dict:
    """Apply damage to a combatant, respecting temp HP. Monsters track HP in combat_state; characters and NPCs are persisted to DB."""  # noqa: E501
    async with db_client.get_session() as db:
        return await combat_service.apply_damage(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            combatant_type=combatant_type,
            amount=amount,
            damage_type=damage_type,
        )


@tool
async def apply_healing(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID or monster id."],
    combatant_type: Annotated[str, '"character", "npc", or "monster".'],
    amount: Annotated[int, "HP to restore."],
) -> dict:
    """Heal a combatant by amount, not exceeding max HP. Clears unconscious/death save status for characters."""  # noqa: E501
    async with db_client.get_session() as db:
        return await combat_service.apply_healing(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            combatant_type=combatant_type,
            amount=amount,
        )


@tool
async def apply_condition(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID or monster id."],
    combatant_type: Annotated[str, '"character", "npc", or "monster".'],
    condition: Annotated[str, "The condition name."],
) -> dict:
    """Apply a condition to a combatant (e.g. "poisoned", "blinded", "prone", "stunned"). Tracked in combat_state for all types."""  # noqa: E501
    async with db_client.get_session() as db:
        return await combat_service.apply_condition(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            condition=condition,
        )


@tool
async def remove_condition(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID or monster id."],
    combatant_type: Annotated[str, '"character", "npc", or "monster".'],
    condition: Annotated[str, "The condition to remove."],
) -> dict:
    """Remove a condition from a combatant."""
    async with db_client.get_session() as db:
        return await combat_service.remove_condition(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            condition=condition,
        )


@tool
async def roll_death_save(
    session_id: Annotated[str, "The session UUID."],
    character_id: Annotated[str, "The character's UUID."],
) -> dict:
    """Roll a death saving throw for an unconscious character at 0 HP. Only valid for player characters — NPCs/monsters die at 0 HP."""  # noqa: E501
    async with db_client.get_session() as db:
        return await combat_service.roll_death_save(
            db,
            session_id=uuid.UUID(session_id),
            character_id=character_id,
        )


@tool
async def advance_turn(
    session_id: Annotated[str, "The session UUID."],
) -> dict:
    """Advance to the next combatant's turn, skipping dead combatants. Increments round when order wraps. Returns end_of_turn_ticks, start_of_turn_ticks, and expired_effects."""  # noqa: E501
    async with db_client.get_session() as db:
        return await combat_service.advance_turn(db, session_id=uuid.UUID(session_id))


@tool
async def apply_effect(
    session_id: Annotated[str, "The session UUID."],
    target_id: Annotated[str, "Combatant ID the effect applies to."],
    effect_name: Annotated[str, 'Human-readable name, e.g. "Hold Person", "Bless", "Poison".'],
    duration_rounds: Annotated[int, "How many rounds the effect lasts."],
    tick: Annotated[str, '"start_of_target_turn", "end_of_target_turn", or "" for passive.'] = "",
    save_ability: Annotated[str, 'Ability for repeating save, e.g. "wis". Empty if no save.'] = "",
    save_dc: Annotated[int, "DC for the repeating save. 0 if no save."] = 0,
    condition: Annotated[
        str, 'Condition applied by this effect, e.g. "paralyzed". Empty if none.'
    ] = "",
    damage: Annotated[str, 'Tick damage dice, e.g. "1d6". Empty if no tick damage.'] = "",
    damage_type: Annotated[str, 'Damage type for tick damage, e.g. "poison".'] = "",
    mechanical_notes: Annotated[str, "Free-text notes on how to resolve ticks."] = "",
    source_id: Annotated[str, "Combatant ID of the caster or source. Optional."] = "",
) -> dict:
    """Track a multi-round effect (concentration spell, poison, regen). tick controls when advance_turn returns reminders."""  # noqa: E501
    async with db_client.get_session() as db:
        return await combat_service.apply_effect(
            db,
            session_id=uuid.UUID(session_id),
            target_id=target_id,
            effect_name=effect_name,
            duration_rounds=duration_rounds,
            tick=tick,
            save_ability=save_ability,
            save_dc=save_dc,
            condition=condition,
            damage=damage,
            damage_type=damage_type,
            mechanical_notes=mechanical_notes,
            source_id=source_id,
        )


@tool
async def remove_effect(
    session_id: Annotated[str, "The session UUID."],
    effect_id: Annotated[str, "The effect's UUID (from the apply_effect response)."],
) -> dict:
    """Remove an active effect by its ID. Call when concentration breaks, dispel magic succeeds, or a repeating save ends the effect."""  # noqa: E501
    async with db_client.get_session() as db:
        return await combat_service.remove_effect(
            db,
            session_id=uuid.UUID(session_id),
            effect_id=effect_id,
        )
