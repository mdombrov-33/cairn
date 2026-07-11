import math
import random
import uuid
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from cairn import srd as rules
from cairn.application.combat.emitter import emit
from cairn.application.combat.rolls import (
    parse_and_roll,
    roll_d20,
    save_modifier,
)
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.combat import CombatEffect, ConcentrationData
from cairn.domain.combat_range import range_feet_to_category, target_in_range, zone_in_range
from cairn.domain.combat_rules import (
    empty_combat_state,
    exhaustion_level,
    find_combatant,
    find_monster,
)
from cairn.domain.services.settings import resolve_settings


async def _death_mode(db: AsyncSession, session_id: uuid.UUID) -> str:
    session = await session_queries.get_session(db, session_id)
    campaign = await campaign_queries.get_campaign(db, session.campaign_id)
    return resolve_settings(campaign.settings).death_mode


async def _concentration_save(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    name: str,
    rec: ConcentrationData,
    con_score: int,
    damage: int,
    incapacitated: bool,
) -> bool:
    """Roll a damage-triggered concentration save. On failure, drop the linked effect and emit.

    Returns True if concentration broke (caller clears the record on the entity).
    """
    dc = max(10, damage // 2)
    if incapacitated:
        broke = True
        total = 0
    else:
        con_mod = math.floor((con_score - 10) / 2)
        total = random.randint(1, 20) + con_mod
        broke = total < dc
    if not broke:
        await emit(db, {"type": "concentration_check_passed", "combatant": name, "dc": dc, "total": total})
        return False
    effect_id = rec.get("source_effect_id")
    if effect_id:
        await remove_effect(db, session_id=session_id, effect_id=effect_id)
    await emit(
        db,
        {"type": "concentration_broken", "combatant": name, "spell": rec.get("spell_name"), "dc": dc, "total": total},
    )
    return True


async def apply_damage(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    combatant_type: str,
    amount: int,
    damage_type: str = "untyped",
    subdue: bool = False,
    attacker_id: str = "",
    weapon_range_ft: int = 0,
) -> dict:
    if subdue and not attacker_id:
        return {"error": "Subdual damage requires attacker_id."}
    if subdue:
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or empty_combat_state()
        if not target_in_range(
            state,
            source_id=attacker_id,
            target_id=combatant_id,
            range_category="touch",
        ):
            return {"error": "Subdual damage requires the attacker and target to share a zone."}
    if attacker_id and weapon_range_ft > 0:
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or empty_combat_state()
        if not target_in_range(
            state,
            source_id=attacker_id,
            target_id=combatant_id,
            range_category=range_feet_to_category(weapon_range_ft),
        ):
            target = find_combatant(state, combatant_id)
            name = target["name"] if target is not None else combatant_id
            return {"error": f"{name} is out of range for a {weapon_range_ft}ft attack."}

    if combatant_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(combatant_id))
        hp_before = char.hp
        effective = max(0, amount - char.temp_hp)
        char.temp_hp = max(0, char.temp_hp - amount)
        new_hp = max(0, char.hp - effective)

        pacifist = (not char.is_companion) and (await _death_mode(db, session_id)) == "pacifist"
        knocked_out = instant_death = False
        if new_hp == 0:
            if pacifist:
                new_hp = 1  # PC never drops in pacifist mode
            elif subdue:
                knocked_out = True
            elif effective - hp_before >= char.max_hp:
                instant_death = True
        char.hp = new_hp

        if instant_death:
            char.status = "dead"
            char.death_save_failures = 3
        elif knocked_out:
            char.death_save_successes = 0
            char.death_save_failures = 0

        result = {
            "combatant": char.name,
            "damage_taken": effective,
            "temp_hp_absorbed": amount - effective,
            "hp": char.hp,
            "is_unconscious": char.hp == 0,
            "is_dead": instant_death,
        }
        if knocked_out:
            result["knocked_out"] = True
        await emit(db, {"type": "damage_applied", "combatant_type": "character", **result})
        if instant_death:
            await emit(db, {"type": "massive_damage_death", "combatant": char.name})
        if knocked_out:
            await emit(db, {"type": "combatant_knocked_out", "combatant": char.name})
        if char.concentration and effective > 0:
            broke = await _concentration_save(
                db,
                session_id=session_id,
                name=char.name,
                rec=char.concentration,
                con_score=char.ability_scores.get("con", 10),
                damage=effective,
                incapacitated=char.hp == 0,
            )
            if broke:
                char.concentration = None
        await db.commit()
        return result

    if combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
        hp_before = npc.hp
        effective = max(0, amount - npc.temp_hp)
        npc.temp_hp = max(0, npc.temp_hp - amount)
        new_hp = max(0, npc.hp - effective)
        knocked_out = subdue and new_hp == 0
        instant_death = (not subdue) and new_hp == 0 and (effective - hp_before >= npc.max_hp)
        npc.hp = new_hp
        is_dead = new_hp == 0 and not knocked_out
        result = {
            "combatant": npc.name,
            "damage_taken": effective,
            "temp_hp_absorbed": amount - effective,
            "hp": npc.hp,
            "is_unconscious": new_hp == 0,
            "is_dead": is_dead,
        }
        if knocked_out:
            result["knocked_out"] = True
        await emit(db, {"type": "damage_applied", "combatant_type": "npc", **result})
        if instant_death:
            await emit(db, {"type": "massive_damage_death", "combatant": npc.name})
        if knocked_out:
            await emit(db, {"type": "combatant_knocked_out", "combatant": npc.name})
        if npc.concentration and effective > 0:
            broke = await _concentration_save(
                db,
                session_id=session_id,
                name=npc.name,
                rec=npc.concentration,
                con_score=npc.ability_scores.get("con", 10),
                damage=effective,
                incapacitated=new_hp == 0,
            )
            if broke:
                npc.concentration = None
        await db.commit()
        return result

    if combatant_type == "monster":
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or empty_combat_state()
        combatant = find_monster(state, combatant_id)
        if combatant is None:
            return {"error": f"Monster '{combatant_id}' not found in combat state."}
        hp_before = combatant["hp"]
        effective = max(0, amount - combatant.get("temp_hp", 0))
        new_hp = max(0, combatant["hp"] - effective)
        knocked_out = subdue and new_hp == 0
        instant_death = (not subdue) and new_hp == 0 and (effective - hp_before >= combatant["max_hp"])
        combatant["hp"] = new_hp
        combatant["is_alive"] = new_hp > 0 or knocked_out
        combatant["is_conscious"] = new_hp > 0
        await session_queries.update_combat_state(
            db, session_id, combat_state=state, combat_active=session.combat_active
        )
        result = {
            "combatant": combatant["name"],
            "damage_taken": effective,
            "hp": combatant["hp"],
            "is_alive": combatant["is_alive"],
            "is_dead": not combatant["is_alive"],
        }
        if knocked_out:
            result["knocked_out"] = True
        await emit(db, {"type": "damage_applied", "combatant_type": "monster", **result})
        if instant_death:
            await emit(db, {"type": "massive_damage_death", "combatant": combatant["name"]})
        if knocked_out:
            await emit(db, {"type": "combatant_knocked_out", "combatant": combatant["name"]})
        conc = combatant.get("concentration")
        if conc and effective > 0:
            monster_data = rules.get_monster(combatant["srd_index"])
            con_score = monster_data.get("constitution", 10) if monster_data else 10
            broke = await _concentration_save(
                db,
                session_id=session_id,
                name=combatant["name"],
                rec=conc,
                con_score=con_score,
                damage=effective,
                incapacitated=new_hp == 0,
            )
            if broke:
                combatant["concentration"] = None
                await session_queries.update_combat_state(
                    db, session_id, combat_state=state, combat_active=session.combat_active
                )
        await db.commit()
        return result

    return {"error": f"Unknown combatant_type '{combatant_type}'."}


async def apply_healing(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    combatant_type: str,
    amount: int,
) -> dict:
    if combatant_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(combatant_id))
        char.hp = min(char.max_hp, char.hp + amount)
        if char.hp > 0:
            char.death_save_successes = 0
            char.death_save_failures = 0
        result = {
            "combatant": char.name,
            "hp": char.hp,
            "max_hp": char.max_hp,
            "is_conscious": char.hp > 0,
        }
        await emit(db, {"type": "healing_applied", "combatant_type": "character", **result})
        await db.commit()
        return result

    if combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
        npc.hp = min(npc.max_hp, npc.hp + amount)
        result = {"combatant": npc.name, "hp": npc.hp, "max_hp": npc.max_hp}
        await emit(db, {"type": "healing_applied", "combatant_type": "npc", **result})
        await db.commit()
        return result

    if combatant_type == "monster":
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or empty_combat_state()
        combatant = find_monster(state, combatant_id)
        if combatant is None:
            return {"error": f"Monster '{combatant_id}' not found in combat state."}
        combatant["hp"] = min(combatant["max_hp"], combatant["hp"] + amount)
        combatant["is_alive"] = True
        combatant["is_conscious"] = True
        await session_queries.update_combat_state(
            db, session_id, combat_state=state, combat_active=session.combat_active
        )
        result = {
            "combatant": combatant["name"],
            "hp": combatant["hp"],
            "max_hp": combatant["max_hp"],
        }
        await emit(db, {"type": "healing_applied", "combatant_type": "monster", **result})
        await db.commit()
        return result

    return {"error": f"Unknown combatant_type '{combatant_type}'."}


async def apply_condition(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    condition: str,
) -> dict:
    session = await session_queries.get_session(db, session_id)
    state = session.combat_state or empty_combat_state()
    combatant = find_combatant(state, combatant_id)
    if combatant is None:
        return {"error": f"Combatant '{combatant_id}' not found in combat state."}
    conditions = combatant.setdefault("conditions", [])
    if condition not in conditions:
        conditions.append(condition)
    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=session.combat_active)
    result = {"combatant": combatant["name"], "conditions": conditions}
    await emit(db, {"type": "condition_applied", "condition": condition, **result})
    await db.commit()
    return result


async def remove_condition(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    condition: str,
) -> dict:
    session = await session_queries.get_session(db, session_id)
    state = session.combat_state or empty_combat_state()
    combatant = find_combatant(state, combatant_id)
    if combatant is None:
        return {"error": f"Combatant '{combatant_id}' not found in combat state."}
    combatant["conditions"] = [c for c in combatant.get("conditions", []) if c != condition]
    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=session.combat_active)
    result = {"combatant": combatant["name"], "conditions": combatant["conditions"]}
    await emit(db, {"type": "condition_removed", "condition": condition, **result})
    await db.commit()
    return result


async def apply_effect(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    target_id: str,
    effect_name: str,
    duration_rounds: int,
    tick: str = "",
    save_ability: str = "",
    save_dc: int = 0,
    condition: str = "",
    damage: str = "",
    damage_type: str = "",
    mechanical_notes: str = "",
    source_id: str = "",
) -> dict:
    session = await session_queries.get_session(db, session_id)
    state = session.combat_state or empty_combat_state()
    effects = state.setdefault("effects", [])
    effect: dict = {
        "id": str(uuid.uuid4()),
        "name": effect_name,
        "target_id": target_id,
        "remaining_rounds": duration_rounds,
    }
    if tick:
        effect["tick"] = tick
    if save_ability:
        effect["save"] = {"ability": save_ability, "dc": save_dc}
    if condition:
        effect["condition"] = condition
    if damage:
        effect["damage"] = damage
        effect["damage_type"] = damage_type
    if mechanical_notes:
        effect["mechanical_notes"] = mechanical_notes
    if source_id:
        effect["source_id"] = source_id
    effects.append(cast(CombatEffect, effect))
    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=session.combat_active)
    await emit(
        db,
        {
            "type": "effect_applied",
            "effect_name": effect_name,
            "target_id": target_id,
            "duration_rounds": duration_rounds,
        },
    )
    await db.commit()
    return {"effect_applied": True, "effect": effect}


async def remove_effect(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    effect_id: str,
) -> dict:
    session = await session_queries.get_session(db, session_id)
    state = session.combat_state or empty_combat_state()
    effects = state.get("effects", [])
    removed = next((e for e in effects if e["id"] == effect_id), None)
    if removed is None:
        return {"error": f"Effect '{effect_id}' not found."}
    state["effects"] = [e for e in effects if e["id"] != effect_id]
    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=session.combat_active)
    await emit(db, {"type": "effect_removed", "effect_name": removed["name"]})
    await db.commit()
    return {"effect_removed": True, "effect_name": removed["name"]}


async def cast_concentration_spell(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    caster_id: str,
    caster_type: str,
    spell_name: str,
    level: int,
    target_id: str,
    effect_name: str,
    duration_rounds: int,
    condition: str = "",
    save_ability: str = "",
    save_dc: int = 0,
    tick: str = "",
    damage: str = "",
    damage_type: str = "",
    mechanical_notes: str = "",
    spell_range_ft: int = 0,
) -> dict:
    """Atomically apply a concentration effect and set the caster's concentration record.

    Bundling prevents drift between the concentration record and its linked effect, so the
    damage-triggered auto-save can remove the right effect when concentration breaks.
    """
    if spell_range_ft > 0:
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or empty_combat_state()
        if not target_in_range(
            state,
            source_id=caster_id,
            target_id=target_id,
            range_category=range_feet_to_category(spell_range_ft),
        ):
            target = find_combatant(state, target_id)
            name = target["name"] if target is not None else target_id
            return {"error": f"{name} is out of range for a {spell_range_ft}ft spell."}
    effect_result = await apply_effect(
        db,
        session_id=session_id,
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
        source_id=caster_id,
    )
    effect_id = effect_result["effect"]["id"]
    rec: ConcentrationData = {"spell_name": spell_name, "level": level, "source_effect_id": effect_id}

    if caster_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(caster_id))
        char.concentration = rec
        name = char.name
    elif caster_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(caster_id))
        npc.concentration = rec
        name = npc.name
    elif caster_type == "monster":
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or empty_combat_state()
        combatant = find_monster(state, caster_id)
        if combatant is None:
            return {"error": f"Monster '{caster_id}' not found in combat state."}
        combatant["concentration"] = rec
        name = combatant["name"]
        await session_queries.update_combat_state(
            db, session_id, combat_state=state, combat_active=session.combat_active
        )
    else:
        return {"error": f"Unknown caster_type '{caster_type}'."}

    await emit(db, {"type": "concentration_started", "combatant": name, "spell": spell_name})
    await db.commit()
    return {"concentrating_on": spell_name, "effect_id": effect_id, "effect": effect_result["effect"]}


async def apply_aoe_damage(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    targets: list[dict],
    damage_dice: str,
    save_ability: str,
    save_dc: int,
    damage_type: str = "untyped",
    half_on_save: bool = True,
    caster_id: str = "",
    origin_zone: str = "",
    spell_range_ft: int = 0,
) -> dict:
    """Roll damage once, then roll a save per target and apply full/half/no damage."""
    cover_by_target: dict[str, int] = {}
    if origin_zone:
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or empty_combat_state()
        zones = {zone["id"]: zone for zone in state["zones"]}
        if origin_zone not in zones:
            return {"error": f"Zone '{origin_zone}' not found."}
        if not caster_id:
            return {"error": "AoE zone targeting requires caster_id."}
        if spell_range_ft > 0 and not zone_in_range(
            state,
            source_id=caster_id,
            target_zone_id=origin_zone,
            range_category=range_feet_to_category(spell_range_ft),
        ):
            return {"error": f"{origin_zone} is out of range for a {spell_range_ft}ft spell."}
        targets = [
            {"id": combatant["id"], "type": combatant["type"]}
            for combatant in state["combatants"]
            if combatant["zone"] == origin_zone
        ]
        cover_by_target = {
            combatant["id"]: zones[combatant["zone"]]["cover_save_bonus"]
            for combatant in state["combatants"]
            if combatant["zone"] in zones
        }
    # Roll damage once — all targets are hit by the same roll.
    damage_roll = parse_and_roll(damage_dice)
    results = []
    for target in targets:
        combatant_id = target["id"]
        combatant_type = target["type"]
        try:
            name, save_mod = await save_modifier(
                db,
                session_id=session_id,
                combatant_id=combatant_id,
                combatant_type=combatant_type,
                ability=save_ability,
            )
        except ValueError as e:
            results.append({"error": str(e), "combatant_id": combatant_id})
            continue

        save_rolls, save_result = roll_d20("normal")
        cover_save_bonus = cover_by_target.get(combatant_id, 0)
        save_total = save_result + save_mod + cover_save_bonus
        saved = save_total >= save_dc

        if saved and half_on_save:
            amount = damage_roll // 2
        elif saved:
            amount = 0
        else:
            amount = damage_roll

        if amount > 0:
            damage_result = await apply_damage(
                db,
                session_id=session_id,
                combatant_id=combatant_id,
                combatant_type=combatant_type,
                amount=amount,
                damage_type=damage_type,
            )
        else:
            damage_result = {"hp_change": 0}

        results.append(
            {
                "combatant": name,
                "save_rolls": save_rolls,
                "save_modifier": save_mod,
                "cover_save_bonus": cover_save_bonus,
                "save_total": save_total,
                "saved": saved,
                "damage": amount,
                **{k: v for k, v in damage_result.items() if k != "combatant"},
            }
        )

    return {
        "damage_dice": damage_dice,
        "damage_roll": damage_roll,
        "save_ability": save_ability,
        "save_dc": save_dc,
        "half_on_save": half_on_save,
        "results": results,
        **({"origin_zone": origin_zone} if origin_zone else {}),
    }


async def add_exhaustion(
    db: AsyncSession,
    *,
    character_id: str,
    levels: int = 1,
) -> dict:
    char = await character_queries.get_character(db, uuid.UUID(character_id))
    conditions: list = list(char.conditions or [])
    current = exhaustion_level(conditions)
    new_level = min(6, current + levels)

    # Replace existing exhaustion entry or add one.
    conditions = [c for c in conditions if not (isinstance(c, str) and c.startswith("exhaustion-"))]
    if new_level >= 6:
        char.hp = 0
        char.status = "dead"
    else:
        conditions.append(f"exhaustion-{new_level}")
    char.conditions = conditions
    await db.commit()
    return {
        "character": char.name,
        "exhaustion_level": new_level,
        "dead": new_level >= 6,
        "conditions": char.conditions,
    }


async def remove_exhaustion(
    db: AsyncSession,
    *,
    character_id: str,
    levels: int = 1,
) -> dict:
    char = await character_queries.get_character(db, uuid.UUID(character_id))
    conditions: list = list(char.conditions or [])
    current = exhaustion_level(conditions)
    new_level = max(0, current - levels)

    conditions = [c for c in conditions if not (isinstance(c, str) and c.startswith("exhaustion-"))]
    if new_level > 0:
        conditions.append(f"exhaustion-{new_level}")
    char.conditions = conditions
    await db.commit()
    return {
        "character": char.name,
        "exhaustion_level": new_level,
        "conditions": char.conditions,
    }


async def stabilize_character(
    db: AsyncSession,
    *,
    character_id: str,
) -> dict:
    """Stabilize a character at 0 HP (e.g. via Spare the Dying or a healer's kit).

    Clears death save counters — no more saves needed until damaged again.
    """
    char = await character_queries.get_character(db, uuid.UUID(character_id))
    if char.hp > 0:
        return {"error": f"{char.name} is not at 0 HP and doesn't need stabilizing."}
    char.death_save_successes = 0
    char.death_save_failures = 0
    await db.commit()
    return {"stabilized": True, "character": char.name, "hp": char.hp}


async def apply_temp_hp(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    combatant_type: str,
    amount: int,
) -> dict:
    """Grant temp HP, replacing current temp HP only if the new amount is higher (PHB p. 198)."""
    if combatant_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(combatant_id))
        replaced = amount > char.temp_hp
        if replaced:
            char.temp_hp = amount
        await db.commit()
        return {"combatant": char.name, "temp_hp": char.temp_hp, "replaced": replaced}

    if combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
        replaced = amount > npc.temp_hp
        if replaced:
            npc.temp_hp = amount
        await db.commit()
        return {"combatant": npc.name, "temp_hp": npc.temp_hp, "replaced": replaced}

    if combatant_type == "monster":
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or empty_combat_state()
        combatant = find_monster(state, combatant_id)
        if combatant is None:
            return {"error": f"Monster '{combatant_id}' not found in combat state."}
        if amount > combatant.get("temp_hp", 0):
            combatant["temp_hp"] = amount
            await session_queries.update_combat_state(
                db, session_id, combat_state=state, combat_active=session.combat_active
            )
            await db.commit()
        return {"combatant": combatant["name"], "temp_hp": combatant.get("temp_hp", 0)}

    return {"error": f"Unknown combatant_type: {combatant_type!r}"}
