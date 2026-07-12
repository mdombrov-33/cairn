import uuid
from typing import Annotated, Literal

import cairn.application.resources as resource_service
import cairn.application.rests as rest_service
from cairn.db import client as db_client
from cairn.tools.registry import register
from cairn.tools.types import ToolUUID


@register
async def adjust_spell_slot(
    character_id: Annotated[str, "The character's UUID."],
    level: Annotated[int, "Spell slot level to adjust (1-9)."],
    delta: Annotated[int, "Negative to consume slots; positive to restore slots."],
) -> dict:
    """Consume or restore spell slots of one level. Delta must not be zero."""
    if delta == 0:
        return {"error": "delta must not be zero."}
    async with db_client.get_session() as db:
        if delta < 0:
            return await resource_service.consume_spell_slot(
                db,
                character_id=uuid.UUID(character_id),
                level=level,
                count=-delta,
            )
        return await resource_service.restore_spell_slot(
            db,
            character_id=uuid.UUID(character_id),
            level=level,
            count=delta,
        )


@register
async def adjust_resource(
    character_id: Annotated[str, "The character's UUID."],
    resource: Annotated[str, 'Resource key, e.g. "action_surge", "ki", "rage", "bardic_inspiration".'],
    delta: Annotated[int, "Negative to spend uses; positive to restore uses."],
) -> dict:
    """Spend or restore uses of a class resource. Delta must not be zero."""
    if delta == 0:
        return {"error": "delta must not be zero."}
    async with db_client.get_session() as db:
        if delta < 0:
            return await resource_service.use_resource(
                db,
                character_id=uuid.UUID(character_id),
                resource=resource,
                count=-delta,
            )
        return await resource_service.restore_resource(
            db,
            character_id=uuid.UUID(character_id),
            resource=resource,
            count=delta,
        )


@register
async def set_concentration(
    character_id: Annotated[str, "The character's UUID."],
    spell_name: Annotated[str, 'Name of the spell, e.g. "Bless", "Haste", "Hold Person".'],
) -> dict:
    """Begin concentrating on a spell. Automatically drops any previous concentration."""
    async with db_client.get_session() as db:
        return await resource_service.set_concentration(db, character_id=uuid.UUID(character_id), spell_name=spell_name)


@register
async def drop_concentration(
    character_id: Annotated[str, "The character's UUID."],
) -> dict:
    """End a character's concentration.

    Call when they choose to drop it, fail a save, cast another concentration spell, or die.
    """
    async with db_client.get_session() as db:
        return await resource_service.drop_concentration(db, character_id=uuid.UUID(character_id))


@register
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


@register
async def use_economy(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID."],
    economy_type: Annotated[
        Literal["action", "bonus_action", "reaction"],
        "The turn-economy resource to spend.",
    ],
) -> dict:
    """Mark an action, bonus action, or reaction as used for a combatant."""
    fields: dict[str, resource_service.EconomyFlag] = {
        "action": "action_used",
        "bonus_action": "bonus_action_used",
        "reaction": "reaction_used",
    }
    async with db_client.get_session() as db:
        return await resource_service.spend_economy(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            field=fields[economy_type],
        )


@register
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


@register
async def apply_short_rest(
    session_id: Annotated[ToolUUID, "The session UUID."],
) -> dict:
    """Take a short rest for the whole party.

    Resets short-rest resources (Action Surge, Ki, Channel Divinity, etc.) and
    restores Warlock spell slots. Takes ~1 hour of in-game time. Blocked during combat.
    """
    async with db_client.get_session() as db:
        return await rest_service.apply_short_rest(db, session_id=uuid.UUID(session_id))


@register
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


@register
async def roll_hit_die(
    character_id: Annotated[ToolUUID, "The character's UUID."],
) -> dict:
    """Spend one hit die to heal during a short rest.

    Rolls d{hit_die_size} + CON modifier (minimum 1 HP gained). Call repeatedly
    — the player decides when to stop spending dice.
    """
    async with db_client.get_session() as db:
        return dict(await rest_service.roll_hit_die(db, character_id=uuid.UUID(character_id)))
