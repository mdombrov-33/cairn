import json
import uuid
from typing import Annotated

from langchain_core.tools import tool

import cairn.domain.services.combat as combat_service
import cairn.domain.services.leveling as leveling_service
from cairn.db import client as db_client


@tool
async def start_combat(
    session_id: Annotated[str, "The session UUID."],
    enemies_json: Annotated[
        str,
        "JSON array of enemies. Each entry: "
        '{"type": "monster", "name": "goblin", "count": 2} or {"type": "npc", "id": "<uuid>", "team": "enemies"}.',
    ],
) -> dict:
    """Initialize a combat encounter. Rolls initiative for all combatants.

    Party members enrolled automatically. enemies_json is a JSON array of enemy descriptors.
    """
    try:
        enemies = json.loads(enemies_json)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid enemies_json: {e}"}

    async with db_client.get_session() as db:
        combat_state = await combat_service.state.init_state(db, uuid.UUID(session_id), enemies)
    return {"combat_started": True, "combat_state": combat_state}


@tool
async def move_combatant(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant ID to move."],
    target_zone: Annotated[str, "The destination zone id."],
) -> dict:
    """Move a combatant to a reachable tactical zone using its remaining Speed."""
    async with db_client.get_session() as db:
        return await combat_service.zones.move_combatant(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            target_zone_id=target_zone,
        )


@tool
async def get_combatants_in_zone(
    session_id: Annotated[str, "The session UUID."],
    zone_id: Annotated[str, "The zone id whose occupants to return."],
) -> dict:
    """Return every combatant currently occupying one tactical zone."""
    async with db_client.get_session() as db:
        return await combat_service.zones.combatants_in_zone(db, session_id=uuid.UUID(session_id), zone_id=zone_id)


@tool
async def get_zones_in_range(
    session_id: Annotated[str, "The session UUID."],
    from_zone: Annotated[str, "The origin zone id."],
    range_category: Annotated[str, 'Either "close" or "far".'],
) -> dict:
    """Return zones connected to an origin at exactly the requested range category."""
    async with db_client.get_session() as db:
        return await combat_service.zones.zones_in_range(
            db,
            session_id=uuid.UUID(session_id),
            from_zone_id=from_zone,
            range_category=range_category,
        )


@tool
async def end_combat(
    session_id: Annotated[str, "The session UUID."],
    outcome: Annotated[str, '"victory", "defeat", "retreat", or "resolved" (peaceful end).'],
) -> dict:
    """End the current combat encounter and clear combat state."""
    async with db_client.get_session() as db:
        await combat_service.state.end_state(db, session_id=uuid.UUID(session_id))
    return {"combat_ended": True, "outcome": outcome}


@tool
async def apply_damage(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's ID (UUID for character/npc, generated id for monster)."],
    combatant_type: Annotated[str, '"character", "npc", or "monster".'],
    amount: Annotated[int, "Raw damage amount before temp HP absorption."],
    damage_type: Annotated[str, 'Damage type for narrative purposes, e.g. "fire", "slashing".'] = "untyped",
    subdue: Annotated[
        bool, "True for a non-lethal knockout blow (melee only). Drops target to 0 HP, unconscious."
    ] = False,
    attacker_id: Annotated[str, "Attacker combatant id. Omit for environmental or ongoing damage."] = "",
    weapon_range_ft: Annotated[int, "Weapon range in feet. Omit for environmental or ongoing damage."] = 0,
) -> dict:
    """Apply damage to a combatant, respecting temp HP.

    Monsters track HP in combat_state; characters and NPCs are persisted to DB.
    Concentration saves auto-fire on damage. Set subdue=True to knock out instead of kill (melee only).
    """
    async with db_client.get_session() as db:
        return await combat_service.mutations.apply_damage(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            combatant_type=combatant_type,
            amount=amount,
            damage_type=damage_type,
            subdue=subdue,
            attacker_id=attacker_id,
            weapon_range_ft=weapon_range_ft,
        )


@tool
async def apply_healing(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID or monster id."],
    combatant_type: Annotated[str, '"character", "npc", or "monster".'],
    amount: Annotated[int, "HP to restore."],
) -> dict:
    """Heal a combatant by amount, not exceeding max HP. Clears unconscious/death save status for characters."""
    async with db_client.get_session() as db:
        return await combat_service.mutations.apply_healing(
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
    condition: Annotated[str, "The condition name."],
) -> dict:
    """Apply a condition to a combatant (e.g. "poisoned", "blinded", "prone", "stunned").

    Tracked in combat_state for all combatant types.
    """
    async with db_client.get_session() as db:
        return await combat_service.mutations.apply_condition(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            condition=condition,
        )


@tool
async def remove_condition(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID or monster id."],
    condition: Annotated[str, "The condition to remove."],
) -> dict:
    """Remove a condition from a combatant."""
    async with db_client.get_session() as db:
        return await combat_service.mutations.remove_condition(
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
    """Roll a death saving throw for an unconscious character at 0 HP.

    Only valid for player characters — NPCs/monsters die at 0 HP.
    """
    async with db_client.get_session() as db:
        return await combat_service.rolls.roll_death_save(
            db,
            session_id=uuid.UUID(session_id),
            character_id=character_id,
        )


@tool
async def advance_turn(
    session_id: Annotated[str, "The session UUID."],
) -> dict:
    """Advance to the next combatant's turn, skipping dead combatants.

    Increments round when order wraps. Returns end_of_turn_ticks, start_of_turn_ticks, and expired_effects.
    """
    async with db_client.get_session() as db:
        return await combat_service.state.advance_turn(db, session_id=uuid.UUID(session_id))


@tool
async def apply_effect(
    session_id: Annotated[str, "The session UUID."],
    target_id: Annotated[str, "Combatant ID the effect applies to."],
    effect_name: Annotated[str, 'Human-readable name, e.g. "Hold Person", "Bless", "Poison".'],
    duration_rounds: Annotated[int, "How many rounds the effect lasts."],
    tick: Annotated[str, '"start_of_target_turn", "end_of_target_turn", or "" for passive.'] = "",
    save_ability: Annotated[str, 'Ability for repeating save, e.g. "wis". Empty if no save.'] = "",
    save_dc: Annotated[int, "DC for the repeating save. 0 if no save."] = 0,
    condition: Annotated[str, 'Condition applied by this effect, e.g. "paralyzed". Empty if none.'] = "",
    damage: Annotated[str, 'Tick damage dice, e.g. "1d6". Empty if no tick damage.'] = "",
    damage_type: Annotated[str, 'Damage type for tick damage, e.g. "poison".'] = "",
    mechanical_notes: Annotated[str, "Free-text notes on how to resolve ticks."] = "",
    source_id: Annotated[str, "Combatant ID of the caster or source. Optional."] = "",
) -> dict:
    """Track a multi-round effect (concentration spell, poison, regen).

    tick controls when advance_turn returns reminders.
    """
    async with db_client.get_session() as db:
        return await combat_service.mutations.apply_effect(
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
    """Remove an active effect by its ID.

    Call when concentration breaks, dispel magic succeeds, or a repeating save ends the effect.
    """
    async with db_client.get_session() as db:
        return await combat_service.mutations.remove_effect(
            db,
            session_id=uuid.UUID(session_id),
            effect_id=effect_id,
        )


@tool
async def cast_concentration_spell(
    session_id: Annotated[str, "The session UUID."],
    caster_id: Annotated[str, "The caster's combatant ID (UUID for character/npc, monster id for monsters)."],
    caster_type: Annotated[str, '"character", "npc", or "monster".'],
    spell_name: Annotated[str, 'The spell, e.g. "Hold Person".'],
    level: Annotated[int, "The slot level the spell is cast at."],
    target_id: Annotated[str, "Combatant ID the effect applies to."],
    effect_name: Annotated[str, "Effect name, usually the spell name."],
    duration_rounds: Annotated[int, "How many rounds the effect lasts."],
    condition: Annotated[str, 'Condition imposed, e.g. "paralyzed". Empty if none.'] = "",
    save_ability: Annotated[str, 'Ability for the repeating save, e.g. "wis". Empty if none.'] = "",
    save_dc: Annotated[int, "DC for the repeating save. 0 if none."] = 0,
    tick: Annotated[str, '"start_of_target_turn", "end_of_target_turn", or "" for passive.'] = "",
    damage: Annotated[str, 'Tick damage dice, e.g. "1d6". Empty if none.'] = "",
    damage_type: Annotated[str, "Damage type for tick damage."] = "",
    mechanical_notes: Annotated[str, "Free-text notes on how to resolve ticks."] = "",
    spell_range_ft: Annotated[int, "Spell range in feet. Omit for non-targeted effects."] = 0,
) -> dict:
    """Cast a concentration spell: apply its effect AND set the caster's concentration in one call.

    Use this for any spell requiring concentration so the auto-save can drop the right effect.
    """
    async with db_client.get_session() as db:
        return await combat_service.mutations.cast_concentration_spell(
            db,
            session_id=uuid.UUID(session_id),
            caster_id=caster_id,
            caster_type=caster_type,
            spell_name=spell_name,
            level=level,
            target_id=target_id,
            effect_name=effect_name,
            duration_rounds=duration_rounds,
            condition=condition,
            save_ability=save_ability,
            save_dc=save_dc,
            tick=tick,
            damage=damage,
            damage_type=damage_type,
            mechanical_notes=mechanical_notes,
            spell_range_ft=spell_range_ft,
        )


@tool
async def roll_saving_throw(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID (character/npc) or monster id."],
    combatant_type: Annotated[str, '"character", "npc", or "monster".'],
    ability: Annotated[str, 'Ability short code: "str", "dex", "con", "int", "wis", or "cha".'],
    dc: Annotated[int, "Difficulty class to beat."],
    roll_type: Annotated[str, '"normal", "advantage", or "disadvantage".'] = "normal",
) -> dict:
    """Roll a saving throw for a combatant against a DC. Returns roll, modifier, total, and pass/fail."""
    async with db_client.get_session() as db:
        return await combat_service.rolls.roll_saving_throw(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            combatant_type=combatant_type,
            ability=ability,
            dc=dc,
            roll_type=roll_type,
        )


@tool
async def add_combatant(
    session_id: Annotated[str, "The session UUID."],
    combatant_type: Annotated[str, '"character", "npc", or "monster".'],
    name_or_id: Annotated[
        str,
        "Character or NPC UUID for character/npc types; monster name (e.g. 'goblin') for monster type.",
    ],
    initiative_roll: Annotated[int, "Pre-rolled initiative total (from roll_initiative)."],
    team: Annotated[str, '"enemies" or "players". Ignored for characters (always players).'] = "enemies",
) -> dict:
    """Add a late-joining combatant to an active combat at the correct initiative position.

    Call roll_initiative first to get the initiative_roll value.
    """
    async with db_client.get_session() as db:
        return await combat_service.state.add_combatant(
            db,
            session_id=uuid.UUID(session_id),
            combatant_type=combatant_type,
            name_or_id=name_or_id,
            initiative_roll=initiative_roll,
            team=team,
        )


@tool
async def remove_combatant(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's combat-state id to remove."],
) -> dict:
    """Remove a combatant from the active initiative order (e.g. flees, is banished, or surrenders).

    Does not kill them — use apply_damage for death.
    """
    async with db_client.get_session() as db:
        return await combat_service.state.remove_combatant(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
        )


@tool
async def award_xp(
    character_id: Annotated[str, "The character's UUID."],
    amount: Annotated[int, "XP to award. Must be non-negative."],
) -> dict:
    """Award XP to a character. Returns new XP total, current level, and whether they're ready to level up."""
    async with db_client.get_session() as db:
        return await leveling_service._award_xp(db, character_id=uuid.UUID(character_id), amount=amount)


@tool
async def add_exhaustion(
    character_id: Annotated[str, "The character's UUID."],
    levels: Annotated[int, "Number of exhaustion levels to add. Default 1."] = 1,
) -> dict:
    """Add exhaustion levels to a character (stored as 'exhaustion-N' in conditions). Level 6 kills the character."""
    async with db_client.get_session() as db:
        return await combat_service.mutations.add_exhaustion(db, character_id=character_id, levels=levels)


@tool
async def remove_exhaustion(
    character_id: Annotated[str, "The character's UUID."],
    levels: Annotated[int, "Number of exhaustion levels to remove. Default 1."] = 1,
) -> dict:
    """Remove exhaustion levels from a character (e.g. after a long rest or Greater Restoration)."""
    async with db_client.get_session() as db:
        return await combat_service.mutations.remove_exhaustion(db, character_id=character_id, levels=levels)


@tool
async def stabilize_character(
    character_id: Annotated[str, "The character's UUID."],
) -> dict:
    """Stabilize an unconscious character at 0 HP (Spare the Dying, healer's kit).

    Clears death save counters so no further saves are needed until they take damage again.
    """
    async with db_client.get_session() as db:
        return await combat_service.mutations.stabilize_character(db, character_id=character_id)


@tool
async def apply_temp_hp(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID (character/npc) or monster combat-state id."],
    combatant_type: Annotated[str, '"character", "npc", or "monster".'],
    amount: Annotated[int, "Temp HP to grant. Replaces current temp HP only if this value is higher."],
) -> dict:
    """Grant temporary HP to a combatant.

    Temp HP never stack — the new amount replaces the old only if it's higher (PHB p. 198).
    """
    async with db_client.get_session() as db:
        return await combat_service.mutations.apply_temp_hp(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            combatant_type=combatant_type,
            amount=amount,
        )


@tool
async def apply_aoe_damage(
    session_id: Annotated[str, "The session UUID."],
    targets_json: Annotated[
        str,
        'JSON array of targets. Each entry: {"id": "<uuid-or-monster-id>", "type": "character|npc|monster"}.',
    ],
    damage_dice: Annotated[str, 'Damage dice expression, e.g. "8d6", "6d8+3".'],
    save_ability: Annotated[str, 'Ability for the saving throw, e.g. "dex", "con", "wis".'],
    save_dc: Annotated[int, "DC for the saving throw."],
    damage_type: Annotated[str, 'Damage type, e.g. "fire", "cold", "thunder".'] = "untyped",
    half_on_save: Annotated[
        bool, "If true, targets take half damage on a successful save. If false, no damage on save."
    ] = True,
    caster_id: Annotated[str, "Caster combatant id when targeting a zone."] = "",
    origin_zone: Annotated[str, "Zone where the area effect lands. Omit for legacy explicit targets."] = "",
    spell_range_ft: Annotated[int, "Spell range in feet when targeting a zone."] = 0,
) -> dict:
    """Apply area-of-effect damage to multiple targets.

    Rolls damage once, then rolls a saving throw per target and applies full, half, or no damage.
    """
    try:
        targets = json.loads(targets_json)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid targets_json: {e}"}

    async with db_client.get_session() as db:
        return await combat_service.mutations.apply_aoe_damage(
            db,
            session_id=uuid.UUID(session_id),
            targets=targets,
            damage_dice=damage_dice,
            save_ability=save_ability,
            save_dc=save_dc,
            damage_type=damage_type,
            half_on_save=half_on_save,
            caster_id=caster_id,
            origin_zone=origin_zone,
            spell_range_ft=spell_range_ft,
        )


@tool
async def resolve_contest(
    session_id: Annotated[str, "The session UUID."],
    attacker_id: Annotated[str, "Attacker's UUID (character/npc) or monster combat-state id."],
    attacker_type: Annotated[str, '"character", "npc", or "monster".'],
    attacker_skill: Annotated[str, 'Skill the attacker uses, e.g. "Athletics", "Deception".'],
    defender_id: Annotated[str, "Defender's UUID (character/npc) or monster combat-state id."],
    defender_type: Annotated[str, '"character", "npc", or "monster".'],
    defender_skill: Annotated[str, 'Skill the defender uses, e.g. "Athletics", "Perception".'],
) -> dict:
    """Resolve an opposed skill contest (e.g. grapple, shove, stealth vs. perception).

    Both sides roll; ties go to the defender per PHB rules.
    """
    async with db_client.get_session() as db:
        return await combat_service.rolls.resolve_contest(
            db,
            session_id=uuid.UUID(session_id),
            attacker_id=attacker_id,
            attacker_type=attacker_type,
            attacker_skill=attacker_skill,
            defender_id=defender_id,
            defender_type=defender_type,
            defender_skill=defender_skill,
        )


@tool
async def roll_initiative(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[
        str,
        "Character/NPC UUID, an existing monster's combat-state id, or a monster name for SRD lookup.",
    ],
    combatant_type: Annotated[str, '"character", "npc", or "monster".'],
    roll_type: Annotated[str, '"normal", "advantage", or "disadvantage".'] = "normal",
) -> dict:
    """Roll initiative (d20 + DEX modifier) for a combatant.

    Returns the initiative total to pass to add_combatant or use when re-inserting into the initiative order.
    """
    async with db_client.get_session() as db:
        return await combat_service.rolls.roll_initiative(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            combatant_type=combatant_type,
            roll_type=roll_type,
        )


@tool
async def roll_skill_check(
    session_id: Annotated[str, "The session UUID."],
    combatant_id: Annotated[str, "The combatant's UUID (character/npc) or monster id."],
    combatant_type: Annotated[str, '"character", "npc", or "monster".'],
    skill: Annotated[
        str,
        'Skill name, e.g. "Perception", "Stealth", "Athletics", "Persuasion", "Investigation".',
    ],
    dc: Annotated[int, "Difficulty class to beat."],
    roll_type: Annotated[str, '"normal", "advantage", or "disadvantage".'] = "normal",
) -> dict:
    """Roll a skill check for a combatant against a DC.

    Applies proficiency bonus if the combatant is proficient. Returns roll, modifier, total, and pass/fail.
    """
    async with db_client.get_session() as db:
        return await combat_service.rolls.roll_skill_check(
            db,
            session_id=uuid.UUID(session_id),
            combatant_id=combatant_id,
            combatant_type=combatant_type,
            skill=skill,
            dc=dc,
            roll_type=roll_type,
        )
