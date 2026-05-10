import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.services.combat.emitter import emit
from cairn.domain.services.combat.helpers import exhaustion_level, find_combatant
from cairn.domain.services.combat.rolls import (
    parse_and_roll,
    roll_d20,
    save_modifier,
)


async def apply_damage(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    combatant_type: str,
    amount: int,
    damage_type: str = "untyped",
) -> dict:
    if combatant_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(combatant_id))
        effective = max(0, amount - char.temp_hp)
        char.temp_hp = max(0, char.temp_hp - amount)
        char.hp = max(0, char.hp - effective)
        result = {
            "combatant": char.name,
            "damage_taken": effective,
            "temp_hp_absorbed": amount - effective,
            "hp": char.hp,
            "is_unconscious": char.hp == 0,
            "is_dead": False,
        }
        await emit(db, {"type": "damage_applied", "combatant_type": "character", **result})
        await db.commit()
        return result

    if combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
        effective = max(0, amount - npc.temp_hp)
        npc.temp_hp = max(0, npc.temp_hp - amount)
        npc.hp = max(0, npc.hp - effective)
        is_dead = npc.hp == 0
        result = {
            "combatant": npc.name,
            "damage_taken": effective,
            "temp_hp_absorbed": amount - effective,
            "hp": npc.hp,
            "is_unconscious": is_dead,
            "is_dead": is_dead,
        }
        await emit(db, {"type": "damage_applied", "combatant_type": "npc", **result})
        await db.commit()
        return result

    if combatant_type == "monster":
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or {}
        combatant = find_combatant(state, combatant_id)
        if combatant is None:
            return {"error": f"Monster '{combatant_id}' not found in combat state."}
        effective = max(0, amount - combatant.get("temp_hp", 0))
        combatant["hp"] = max(0, combatant["hp"] - effective)
        combatant["is_alive"] = combatant["hp"] > 0
        combatant["is_conscious"] = combatant["is_alive"]
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
        await emit(db, {"type": "damage_applied", "combatant_type": "monster", **result})
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
        state = session.combat_state or {}
        combatant = find_combatant(state, combatant_id)
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
    state = session.combat_state or {}
    combatant = find_combatant(state, combatant_id)
    if combatant is None:
        return {"error": f"Combatant '{combatant_id}' not found in combat state."}
    conditions = combatant.setdefault("conditions", [])
    if condition not in conditions:
        conditions.append(condition)
    await session_queries.update_combat_state(
        db, session_id, combat_state=state, combat_active=session.combat_active
    )
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
    state = session.combat_state or {}
    combatant = find_combatant(state, combatant_id)
    if combatant is None:
        return {"error": f"Combatant '{combatant_id}' not found in combat state."}
    combatant["conditions"] = [c for c in combatant.get("conditions", []) if c != condition]
    await session_queries.update_combat_state(
        db, session_id, combat_state=state, combat_active=session.combat_active
    )
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
    state = session.combat_state or {}
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
    effects.append(effect)
    await session_queries.update_combat_state(
        db, session_id, combat_state=state, combat_active=session.combat_active
    )
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
    state = session.combat_state or {}
    effects = state.get("effects", [])
    removed = next((e for e in effects if e["id"] == effect_id), None)
    if removed is None:
        return {"error": f"Effect '{effect_id}' not found."}
    state["effects"] = [e for e in effects if e["id"] != effect_id]
    await session_queries.update_combat_state(
        db, session_id, combat_state=state, combat_active=session.combat_active
    )
    await emit(db, {"type": "effect_removed", "effect_name": removed["name"]})
    await db.commit()
    return {"effect_removed": True, "effect_name": removed["name"]}


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
) -> dict:
    """Roll damage once, then roll a save per target and apply full/half/no damage."""
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
        save_total = save_result + save_mod
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
    """Stabilize a character at 0 HP (e.g. via Spare the Dying or a healer's kit). Clears death save counters — no more saves needed until damaged again."""  # noqa: E501
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
        state = session.combat_state or {}
        combatant = find_combatant(state, combatant_id)
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
