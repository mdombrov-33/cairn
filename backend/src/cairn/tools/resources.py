import uuid
from typing import Annotated

from langchain_core.tools import tool

import cairn.application.resources as resource_service
import cairn.application.rests as rest_service
from cairn.db import client as db_client
from cairn.tools.types import ToolUUID


@tool
async def consume_spell_slot(
    character_id: Annotated[str, "The character's UUID."],
    level: Annotated[int, "Spell slot level to consume (1-9)."],
) -> dict:
    """Consume one spell slot of the given level. Call whenever a character casts a leveled spell (not cantrips)."""
    async with db_client.get_session() as db:
        return await resource_service.consume_spell_slot(db, character_id=uuid.UUID(character_id), level=level)


@tool
async def restore_spell_slot(
    character_id: Annotated[str, "The character's UUID."],
    level: Annotated[int, "Spell slot level to restore (1-9)."],
    count: Annotated[int, "Number of slots to restore. Default 1."] = 1,
) -> dict:
    """Restore spell slots of the given level (e.g. Arcane Recovery, short rest for Warlock)."""
    async with db_client.get_session() as db:
        return await resource_service.restore_spell_slot(
            db, character_id=uuid.UUID(character_id), level=level, count=count
        )


@tool
async def use_resource(
    character_id: Annotated[str, "The character's UUID."],
    resource: Annotated[str, 'Resource key, e.g. "action_surge", "ki", "rage", "bardic_inspiration".'],
    count: Annotated[int, "Number of uses to spend. Default 1."] = 1,
) -> dict:
    """Spend uses of a class resource (Action Surge, Ki, Rage, Superiority Dice, Second Wind, etc.)."""
    async with db_client.get_session() as db:
        return await resource_service.use_resource(
            db, character_id=uuid.UUID(character_id), resource=resource, count=count
        )


@tool
async def restore_resource(
    character_id: Annotated[str, "The character's UUID."],
    resource: Annotated[str, "Resource key to restore."],
    count: Annotated[int, "Number of uses to restore. Default 1."] = 1,
) -> dict:
    """Restore uses of a class resource (e.g. after a short or long rest, or from a feature)."""
    async with db_client.get_session() as db:
        return await resource_service.restore_resource(
            db, character_id=uuid.UUID(character_id), resource=resource, count=count
        )


@tool
async def set_concentration(
    character_id: Annotated[str, "The character's UUID."],
    spell_name: Annotated[str, 'Name of the spell, e.g. "Bless", "Haste", "Hold Person".'],
) -> dict:
    """Begin concentrating on a spell. Automatically drops any previous concentration."""
    async with db_client.get_session() as db:
        return await resource_service.set_concentration(db, character_id=uuid.UUID(character_id), spell_name=spell_name)


@tool
async def drop_concentration(
    character_id: Annotated[str, "The character's UUID."],
) -> dict:
    """End a character's concentration.

    Call when they choose to drop it, fail a save, cast another concentration spell, or die.
    """
    async with db_client.get_session() as db:
        return await resource_service.drop_concentration(db, character_id=uuid.UUID(character_id))


@tool
async def roll_concentration_check(
    character_id: Annotated[str, "The character's UUID."],
    damage_taken: Annotated[int, "Total damage taken that triggered the check."],
) -> dict:
    """Roll a Constitution saving throw to maintain concentration after taking damage.

    DC = max(10, half damage taken).
    """
    async with db_client.get_session() as db:
        return await resource_service.roll_concentration_check(
            db, character_id=uuid.UUID(character_id), damage_taken=damage_taken
        )


@tool
async def use_action(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID."],
) -> dict:
    """Mark a combatant's action as used for this turn (Attack, Cast a Spell, Dash, etc.)."""
    async with db_client.get_session() as db:
        return await resource_service.spend_economy(
            db, session_id=uuid.UUID(session_id), combatant_id=combatant_id, field="action_used"
        )


@tool
async def use_bonus_action(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID."],
) -> dict:
    """Mark a combatant's bonus action as used for this turn (Off-hand Attack, Misty Step, Healing Word, etc.)."""
    async with db_client.get_session() as db:
        return await resource_service.spend_economy(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            field="bonus_action_used",
        )


@tool
async def use_reaction(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID."],
) -> dict:
    """Mark a combatant's reaction as used until the start of their next turn.

    Examples: Opportunity Attack, Shield, Counterspell.
    """
    async with db_client.get_session() as db:
        return await resource_service.spend_economy(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            field="reaction_used",
        )


@tool
async def spend_movement(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID."],
    feet: Annotated[int, "Amount of movement to spend."],
) -> dict:
    """Spend movement for a combatant this turn."""
    async with db_client.get_session() as db:
        return await resource_service.spend_movement(
            db, session_id=uuid.UUID(session_id), combatant_id=combatant_id, feet=feet
        )


@tool
async def apply_short_rest(
    session_id: Annotated[ToolUUID, "The session UUID."],
) -> dict:
    """Take a short rest for the whole party.

    Resets short-rest resources (Action Surge, Ki, Channel Divinity, etc.) and
    restores Warlock spell slots. Takes ~1 hour of in-game time. Blocked during combat.
    """
    async with db_client.get_session() as db:
        return await rest_service.apply_short_rest(db, session_id=uuid.UUID(session_id))


@tool
async def apply_long_rest(
    session_id: Annotated[ToolUUID, "The session UUID."],
) -> dict:
    """Take a long rest for the whole party.

    Restores full HP, all spell slots, all resources, and half max hit dice. Clears
    prepared spells for prepared casters (wizard/cleric/druid/paladin) — they must
    re-prepare after. Advances in-game time by 8 hours. Blocked during combat.
    """
    async with db_client.get_session() as db:
        return await rest_service.apply_long_rest(db, session_id=uuid.UUID(session_id))


@tool
async def roll_hit_die(
    character_id: Annotated[ToolUUID, "The character's UUID."],
) -> dict:
    """Spend one hit die to heal during a short rest.

    Rolls d{hit_die_size} + CON modifier (minimum 1 HP gained). Call repeatedly
    — the player decides when to stop spending dice.
    """
    async with db_client.get_session() as db:
        return dict(await rest_service.roll_hit_die(db, character_id=uuid.UUID(character_id)))
