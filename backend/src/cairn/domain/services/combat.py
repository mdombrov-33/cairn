import math
import random
import re
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn import srd as rules
from cairn.context import current_turn_id
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import party_members as party_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.domain.exceptions import ConflictError, NotFoundError

log = structlog.get_logger()


async def _emit(db: AsyncSession, event: dict) -> None:
    turn_id = current_turn_id.get()
    if turn_id is None:
        return
    try:
        await turn_queries.append_event(db, turn_id, event)
    except Exception as exc:
        log.warning("turn_event_emit_failed", error=str(exc), event_type=event.get("type"))


_ABILITY_LONG = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}

_SKILL_ABILITY: dict[str, str] = {
    "athletics": "str",
    "acrobatics": "dex",
    "sleight of hand": "dex",
    "stealth": "dex",
    "arcana": "int",
    "history": "int",
    "investigation": "int",
    "nature": "int",
    "religion": "int",
    "animal handling": "wis",
    "insight": "wis",
    "medicine": "wis",
    "perception": "wis",
    "survival": "wis",
    "deception": "cha",
    "intimidation": "cha",
    "performance": "cha",
    "persuasion": "cha",
}


def _roll_die(sides: int) -> int:
    return random.randint(1, sides)


def _parse_and_roll(expression: str) -> int:
    match = re.fullmatch(r"(\d+)d(\d+)([+-]\d+)?", expression.strip())
    if not match:
        raise ValueError(f"Invalid dice expression: {expression!r}")
    count, sides = int(match.group(1)), int(match.group(2))
    modifier = int(match.group(3) or 0)
    return sum(_roll_die(sides) for _ in range(count)) + modifier


def _mod(score: int) -> int:
    return math.floor((score - 10) / 2)


def _dex_mod(score: int) -> int:
    return _mod(score)


def _roll_d20(roll_type: str) -> tuple[list[int], int]:
    if roll_type == "advantage":
        r1, r2 = _roll_die(20), _roll_die(20)
        return [r1, r2], max(r1, r2)
    if roll_type == "disadvantage":
        r1, r2 = _roll_die(20), _roll_die(20)
        return [r1, r2], min(r1, r2)
    r = _roll_die(20)
    return [r], r


def _find_combatant(state: dict, combatant_id: str) -> dict | None:
    for c in state.get("combatants", []):
        if c["id"] == combatant_id:
            return c
    return None


# Internal state builder


async def _init_state(
    db: AsyncSession,
    session_id: uuid.UUID,
    enemies: list[dict],
) -> dict:
    """Build and persist initial combat state. No ownership check — callers handle auth."""
    db_session = await session_queries.get_session(db, session_id)
    if db_session.combat_active:
        raise ConflictError("combat is already active for this session", code="combat_active")

    combatants: list[dict] = []

    characters = await party_queries.get_party(db, session_id)
    for char in characters:
        combatants.append(
            {
                "id": str(char.id),
                "type": "character",
                "team": "players",
                "ai_controlled": char.is_companion,
                "name": char.name,
                "initiative_roll": random.randint(1, 20) + char.initiative,
                "initiative_modifier": char.initiative,
                "zone": None,
                "conditions": list(char.conditions),
                "is_alive": char.hp > 0,
                "is_conscious": char.hp > 0,
            }
        )

    for enemy in enemies:
        team = enemy.get("team", "enemies")
        if enemy["type"] == "npc":
            npc = await npc_queries.get_npc(db, uuid.UUID(str(enemy["id"])))
            combatants.append(
                {
                    "id": str(npc.id),
                    "type": "npc",
                    "team": team,
                    "name": npc.name,
                    "initiative_roll": random.randint(1, 20) + npc.initiative,
                    "initiative_modifier": npc.initiative,
                    "zone": None,
                    "conditions": list(npc.conditions),
                    "is_alive": npc.hp > 0,
                    "is_conscious": npc.hp > 0,
                }
            )
        elif enemy["type"] == "monster":
            monster = rules.get_monster(enemy["name"])
            if monster is None:
                raise NotFoundError(
                    f"monster '{enemy['name']}' not found in SRD", code="monster_not_found"
                )
            dex = _dex_mod(monster.get("dexterity", 10))
            ac = monster["armor_class"][0]["value"] if monster.get("armor_class") else 10
            count = max(1, enemy.get("count", 1))
            for i in range(count):
                max_hp = _parse_and_roll(monster["hit_points_roll"])
                label = monster["name"] if count == 1 else f"{monster['name']} {i + 1}"
                combatants.append(
                    {
                        "id": f"monster-{uuid.uuid4()}",
                        "type": "monster",
                        "team": "enemies",
                        "name": label,
                        "srd_index": monster["index"],
                        "initiative_roll": random.randint(1, 20) + dex,
                        "initiative_modifier": dex,
                        "zone": None,
                        "hp": max_hp,
                        "max_hp": max_hp,
                        "ac": ac,
                        "conditions": [],
                        "is_alive": True,
                        "is_conscious": True,
                        "actions": monster.get("actions", []),
                        "special_abilities": monster.get("special_abilities", []),
                    }
                )

    combatants.sort(
        key=lambda c: (c["initiative_roll"], c["initiative_modifier"], random.random()),
        reverse=True,
    )

    combat_state = {
        "round": 1,
        "turn_index": 0,
        "combatants": combatants,
        "effects": [],
    }

    await session_queries.update_combat_state(
        db, session_id, combat_state=combat_state, combat_active=True
    )
    await _emit(db, {"type": "combat_started", "combatant_count": len(combatants)})
    await db.commit()
    return combat_state


# HTTP-facing (ownership-checked)


async def start(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
    enemies: list[dict],
) -> dict:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    return await _init_state(db, session_id, enemies)


async def end(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
    outcome: str,
) -> None:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)

    if not db_session.combat_active:
        raise ConflictError("no active combat for this session", code="combat_not_active")

    await session_queries.update_combat_state(
        db, session_id, combat_state=None, combat_active=False
    )
    await db.commit()


async def get_state(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
) -> dict:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    return {"combat_active": db_session.combat_active, "combat_state": db_session.combat_state}


# Business logic (tool-facing, no ownership check)


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
        await _emit(db, {"type": "damage_applied", "combatant_type": "character", **result})
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
        await _emit(db, {"type": "damage_applied", "combatant_type": "npc", **result})
        await db.commit()
        return result

    if combatant_type == "monster":
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or {}
        combatant = _find_combatant(state, combatant_id)
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
        await _emit(db, {"type": "damage_applied", "combatant_type": "monster", **result})
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
        await _emit(db, {"type": "healing_applied", "combatant_type": "character", **result})
        await db.commit()
        return result

    if combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
        npc.hp = min(npc.max_hp, npc.hp + amount)
        result = {"combatant": npc.name, "hp": npc.hp, "max_hp": npc.max_hp}
        await _emit(db, {"type": "healing_applied", "combatant_type": "npc", **result})
        await db.commit()
        return result

    if combatant_type == "monster":
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or {}
        combatant = _find_combatant(state, combatant_id)
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
        await _emit(db, {"type": "healing_applied", "combatant_type": "monster", **result})
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
    combatant = _find_combatant(state, combatant_id)
    if combatant is None:
        return {"error": f"Combatant '{combatant_id}' not found in combat state."}
    conditions = combatant.setdefault("conditions", [])
    if condition not in conditions:
        conditions.append(condition)
    await session_queries.update_combat_state(
        db, session_id, combat_state=state, combat_active=session.combat_active
    )
    result = {"combatant": combatant["name"], "conditions": conditions}
    await _emit(db, {"type": "condition_applied", "condition": condition, **result})
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
    combatant = _find_combatant(state, combatant_id)
    if combatant is None:
        return {"error": f"Combatant '{combatant_id}' not found in combat state."}
    combatant["conditions"] = [c for c in combatant.get("conditions", []) if c != condition]
    await session_queries.update_combat_state(
        db, session_id, combat_state=state, combat_active=session.combat_active
    )
    result = {"combatant": combatant["name"], "conditions": combatant["conditions"]}
    await _emit(db, {"type": "condition_removed", "condition": condition, **result})
    await db.commit()
    return result


async def roll_death_save(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    character_id: str,
) -> dict:
    char = await character_queries.get_character(db, uuid.UUID(character_id))
    if char.hp > 0:
        return {"error": f"{char.name} is not at 0 HP and doesn't need a death save."}

    roll = random.randint(1, 20)
    outcome = "ongoing"

    if roll == 20:
        char.hp = 1
        char.death_save_successes = 0
        char.death_save_failures = 0
        outcome = "stabilized_miraculous"
    elif roll == 1:
        char.death_save_failures = min(3, char.death_save_failures + 2)
    elif roll >= 10:
        char.death_save_successes = min(3, char.death_save_successes + 1)
    else:
        char.death_save_failures = min(3, char.death_save_failures + 1)

    if outcome == "ongoing":
        if char.death_save_failures >= 3:
            outcome = "dead"
        elif char.death_save_successes >= 3:
            outcome = "stable"

    result = {
        "character": char.name,
        "roll": roll,
        "success": roll >= 10,
        "natural_20": roll == 20,
        "natural_1": roll == 1,
        "total_successes": char.death_save_successes,
        "total_failures": char.death_save_failures,
        "outcome": outcome,
        "hp": char.hp,
    }
    await _emit(db, {"type": "death_save_rolled", **result})
    await db.commit()
    return result


async def advance_turn(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> dict:
    session = await session_queries.get_session(db, session_id)
    if not session.combat_active or not session.combat_state:
        return {"error": "No active combat."}

    state = session.combat_state
    combatants = state["combatants"]
    alive = [c for c in combatants if c.get("is_alive", True)]
    if not alive:
        return {"error": "No living combatants remain."}

    outgoing = combatants[state["turn_index"]]

    effects = state.setdefault("effects", [])
    end_of_turn_ticks: list[dict] = []
    expired_effects: list[str] = []
    surviving: list[dict] = []
    for effect in effects:
        if effect["target_id"] == outgoing["id"]:
            if effect.get("tick") == "end_of_target_turn":
                end_of_turn_ticks.append(effect)
            effect["remaining_rounds"] -= 1
            if effect["remaining_rounds"] <= 0:
                expired_effects.append(effect["name"])
                continue
        surviving.append(effect)
    state["effects"] = surviving

    state["turn_index"] = (state["turn_index"] + 1) % len(combatants)
    checked = 0
    while not combatants[state["turn_index"]].get("is_alive", True):
        state["turn_index"] = (state["turn_index"] + 1) % len(combatants)
        checked += 1
        if checked >= len(combatants):
            return {"error": "All combatants are dead."}

    if state["turn_index"] == 0:
        state["round"] = state.get("round", 1) + 1

    current = combatants[state["turn_index"]]
    start_of_turn_ticks = [
        e
        for e in state["effects"]
        if e["target_id"] == current["id"] and e.get("tick") == "start_of_target_turn"
    ]

    economy = state.setdefault("turn_economy", {})
    economy[current["id"]] = {
        "action_used": False,
        "bonus_action_used": False,
        "reaction_used": False,
        "movement_remaining": current.get("speed", 30),
    }

    await session_queries.update_combat_state(
        db, session_id, combat_state=state, combat_active=True
    )

    result: dict = {
        "round": state["round"],
        "turn_index": state["turn_index"],
        "current_combatant": current["name"],
        "current_combatant_type": current["type"],
        "current_combatant_id": current["id"],
    }
    if end_of_turn_ticks:
        result["end_of_turn_ticks"] = end_of_turn_ticks
    if expired_effects:
        result["expired_effects"] = expired_effects
    if start_of_turn_ticks:
        result["start_of_turn_ticks"] = start_of_turn_ticks

    await _emit(
        db,
        {
            "type": "turn_advanced",
            "round": state["round"],
            "current_combatant": current["name"],
            "expired_effects": expired_effects,
        },
    )
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
    await _emit(
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
    await _emit(db, {"type": "effect_removed", "effect_name": removed["name"]})
    await db.commit()
    return {"effect_removed": True, "effect_name": removed["name"]}


async def _end_state(db: AsyncSession, *, session_id: uuid.UUID) -> None:
    """Clear combat state without ownership check — for tool-facing use."""
    await session_queries.update_combat_state(
        db, session_id, combat_state=None, combat_active=False
    )
    await db.commit()


async def roll_saving_throw(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    combatant_type: str,
    ability: str,
    dc: int,
    roll_type: str = "normal",
) -> dict:
    try:
        name, modifier = await _save_modifier(
            db,
            session_id=session_id,
            combatant_id=combatant_id,
            combatant_type=combatant_type,
            ability=ability,
        )
    except ValueError as e:
        return {"error": str(e)}

    rolls, result = _roll_d20(roll_type)
    total = result + modifier
    return {
        "combatant": name,
        "ability": ability,
        "roll_type": roll_type,
        "rolls": rolls,
        "modifier": modifier,
        "total": total,
        "dc": dc,
        "success": total >= dc,
    }


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
    damage_roll = _parse_and_roll(damage_dice)
    results = []
    for target in targets:
        combatant_id = target["id"]
        combatant_type = target["type"]
        try:
            name, save_mod = await _save_modifier(
                db,
                session_id=session_id,
                combatant_id=combatant_id,
                combatant_type=combatant_type,
                ability=save_ability,
            )
        except ValueError as e:
            results.append({"error": str(e), "combatant_id": combatant_id})
            continue

        save_rolls, save_result = _roll_d20("normal")
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


async def add_combatant(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_type: str,
    name_or_id: str,
    initiative_roll: int,
    team: str = "enemies",
) -> dict:
    """Insert a late-joining combatant into an active combat at the correct initiative position."""
    session = await session_queries.get_session(db, session_id)
    if not session.combat_active or not session.combat_state:
        return {"error": "No active combat."}

    state = session.combat_state
    combatants = state["combatants"]

    if combatant_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(name_or_id))
        entry: dict = {
            "id": str(char.id),
            "type": "character",
            "team": "players",
            "ai_controlled": char.is_companion,
            "name": char.name,
            "initiative_roll": initiative_roll,
            "initiative_modifier": char.initiative,
            "zone": None,
            "conditions": list(char.conditions),
            "is_alive": char.hp > 0,
            "is_conscious": char.hp > 0,
        }
    elif combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(name_or_id))
        entry = {
            "id": str(npc.id),
            "type": "npc",
            "team": team,
            "name": npc.name,
            "initiative_roll": initiative_roll,
            "initiative_modifier": npc.initiative,
            "zone": None,
            "conditions": list(npc.conditions),
            "is_alive": npc.hp > 0,
            "is_conscious": npc.hp > 0,
        }
    elif combatant_type == "monster":
        monster = rules.get_monster(name_or_id)
        if monster is None:
            return {"error": f"Monster '{name_or_id}' not found in SRD."}
        max_hp = _parse_and_roll(monster["hit_points_roll"])
        ac = monster["armor_class"][0]["value"] if monster.get("armor_class") else 10
        entry = {
            "id": f"monster-{uuid.uuid4()}",
            "type": "monster",
            "team": team,
            "name": monster["name"],
            "srd_index": monster["index"],
            "initiative_roll": initiative_roll,
            "initiative_modifier": _dex_mod(monster.get("dexterity", 10)),
            "zone": None,
            "hp": max_hp,
            "max_hp": max_hp,
            "ac": ac,
            "conditions": [],
            "is_alive": True,
            "is_conscious": True,
            "actions": monster.get("actions", []),
            "special_abilities": monster.get("special_abilities", []),
        }
    else:
        return {"error": f"Unknown combatant_type: {combatant_type!r}"}

    insert_idx = next(
        (i for i, c in enumerate(combatants) if initiative_roll > c["initiative_roll"]),
        len(combatants),
    )
    combatants.insert(insert_idx, entry)

    # Keep turn_index pointing at the same combatant after insertion.
    if insert_idx <= state["turn_index"]:
        state["turn_index"] += 1

    await session_queries.update_combat_state(
        db, session_id, combat_state=state, combat_active=True
    )
    await _emit(
        db, {"type": "combatant_added", "name": entry["name"], "initiative": initiative_roll}
    )
    await db.commit()
    return {
        "combatant_added": True,
        "combatant": entry["name"],
        "combatant_id": entry["id"],
        "initiative_roll": initiative_roll,
        "position": insert_idx,
    }


async def remove_combatant(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
) -> dict:
    """Remove a combatant from active combat, keeping turn_index consistent."""
    session = await session_queries.get_session(db, session_id)
    if not session.combat_active or not session.combat_state:
        return {"error": "No active combat."}

    state = session.combat_state
    combatants = state["combatants"]
    idx = next((i for i, c in enumerate(combatants) if c["id"] == combatant_id), None)
    if idx is None:
        return {"error": f"Combatant '{combatant_id}' not found in combat state."}

    removed = combatants.pop(idx)

    # Keep turn_index pointing at the same combatant (or wrap safely).
    if idx < state["turn_index"]:
        state["turn_index"] -= 1
    elif idx == state["turn_index"]:
        # Removed the active combatant — land on whoever is next (or wrap to 0).
        state["turn_index"] = state["turn_index"] % len(combatants) if combatants else 0

    await session_queries.update_combat_state(
        db, session_id, combat_state=state, combat_active=True
    )
    await _emit(db, {"type": "combatant_removed", "name": removed["name"]})
    await db.commit()
    return {"combatant_removed": True, "combatant": removed["name"]}


async def _save_modifier(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    combatant_type: str,
    ability: str,
) -> tuple[str, int]:
    """Return (name, save_modifier) for a combatant. Shared by roll_saving_throw and apply_aoe_damage."""  # noqa: E501
    if combatant_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(combatant_id))
        modifier = _mod(char.ability_scores.get(ability, 10))
        if f"saving-throw-{ability}" in (char.saving_throw_proficiencies or []):
            modifier += char.proficiency_bonus
        return char.name, modifier

    if combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
        modifier = _mod(npc.ability_scores.get(ability, 10))
        if f"saving-throw-{ability}" in (npc.saving_throw_proficiencies or []):
            modifier += npc.proficiency_bonus
        return npc.name, modifier

    if combatant_type == "monster":
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or {}
        combatant = _find_combatant(state, combatant_id)
        if combatant is None:
            raise ValueError(f"Monster '{combatant_id}' not found in combat state.")
        monster_data = rules.get_monster(combatant["srd_index"])
        if monster_data is None:
            raise ValueError(f"Monster SRD data not found for '{combatant['srd_index']}'.")
        prof_entry = next(
            (
                p
                for p in monster_data.get("proficiencies", [])
                if p["proficiency"]["index"] == f"saving-throw-{ability}"
            ),
            None,
        )
        modifier = (
            prof_entry["value"]
            if prof_entry
            else _mod(monster_data.get(_ABILITY_LONG[ability], 10))
        )  # noqa: E501
        return combatant["name"], modifier

    raise ValueError(f"Unknown combatant_type: {combatant_type!r}")


async def _skill_modifier(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    combatant_type: str,
    skill: str,
) -> tuple[str, int]:
    """Return (name, skill_modifier) for a combatant. Shared by roll_skill_check and resolve_contest."""  # noqa: E501
    skill_key = skill.lower()
    ability = _SKILL_ABILITY.get(skill_key)
    if ability is None:
        raise ValueError(f"Unknown skill: {skill!r}")

    if combatant_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(combatant_id))
        score = char.ability_scores.get(ability, 10)
        modifier = _mod(score)
        if any(s.lower() == skill_key for s in (char.skill_proficiencies or [])):
            modifier += char.proficiency_bonus
        return char.name, modifier

    if combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
        score = npc.ability_scores.get(ability, 10)
        modifier = _mod(score)
        if any(s.lower() == skill_key for s in (npc.skill_proficiencies or [])):
            modifier += npc.proficiency_bonus
        return npc.name, modifier

    if combatant_type == "monster":
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or {}
        combatant = _find_combatant(state, combatant_id)
        if combatant is None:
            raise ValueError(f"Monster '{combatant_id}' not found in combat state.")
        monster_data = rules.get_monster(combatant["srd_index"])
        if monster_data is None:
            raise ValueError(f"Monster SRD data not found for '{combatant['srd_index']}'.")
        skill_index = f"skill-{skill_key.replace(' ', '-')}"
        prof_entry = next(
            (
                p
                for p in monster_data.get("proficiencies", [])
                if p["proficiency"]["index"] == skill_index
            ),
            None,
        )
        if prof_entry is not None:
            modifier = prof_entry["value"]
        else:
            modifier = _mod(monster_data.get(_ABILITY_LONG[ability], 10))
        return combatant["name"], modifier

    raise ValueError(f"Unknown combatant_type: {combatant_type!r}")


async def resolve_contest(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    attacker_id: str,
    attacker_type: str,
    attacker_skill: str,
    defender_id: str,
    defender_type: str,
    defender_skill: str,
) -> dict:
    try:
        attacker_name, atk_mod = await _skill_modifier(
            db,
            session_id=session_id,
            combatant_id=attacker_id,
            combatant_type=attacker_type,
            skill=attacker_skill,
        )
        defender_name, def_mod = await _skill_modifier(
            db,
            session_id=session_id,
            combatant_id=defender_id,
            combatant_type=defender_type,
            skill=defender_skill,
        )
    except ValueError as e:
        return {"error": str(e)}

    atk_rolls, atk_result = _roll_d20("normal")
    def_rolls, def_result = _roll_d20("normal")
    atk_total = atk_result + atk_mod
    def_total = def_result + def_mod

    # Ties go to the defender (PHB p. 174).
    winner = attacker_name if atk_total > def_total else defender_name
    return {
        "attacker": attacker_name,
        "attacker_skill": attacker_skill,
        "attacker_rolls": atk_rolls,
        "attacker_modifier": atk_mod,
        "attacker_total": atk_total,
        "defender": defender_name,
        "defender_skill": defender_skill,
        "defender_rolls": def_rolls,
        "defender_modifier": def_mod,
        "defender_total": def_total,
        "winner": winner,
        "tied": atk_total == def_total,
    }


async def roll_initiative(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    combatant_type: str,
    roll_type: str = "normal",
) -> dict:
    if combatant_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(combatant_id))
        modifier = char.initiative
        name = char.name

    elif combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
        modifier = npc.initiative
        name = npc.name

    elif combatant_type == "monster":
        # Try existing combatant in state first, then fall back to SRD lookup by name.
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or {}
        combatant = _find_combatant(state, combatant_id)
        if combatant is not None:
            modifier = combatant["initiative_modifier"]
            name = combatant["name"]
        else:
            monster_data = rules.get_monster(combatant_id)
            if monster_data is None:
                return {"error": f"Monster '{combatant_id}' not found in combat state or SRD."}
            modifier = _dex_mod(monster_data.get("dexterity", 10))
            name = monster_data["name"]

    else:
        return {"error": f"Unknown combatant_type: {combatant_type!r}"}

    rolls, result = _roll_d20(roll_type)
    total = result + modifier
    return {
        "combatant": name,
        "roll_type": roll_type,
        "rolls": rolls,
        "modifier": modifier,
        "initiative": total,
    }


async def roll_skill_check(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    combatant_type: str,
    skill: str,
    dc: int,
    roll_type: str = "normal",
) -> dict:
    if skill.lower() not in _SKILL_ABILITY:
        return {"error": f"Unknown skill: {skill!r}. Valid skills: {sorted(_SKILL_ABILITY)}"}
    try:
        name, modifier = await _skill_modifier(
            db,
            session_id=session_id,
            combatant_id=combatant_id,
            combatant_type=combatant_type,
            skill=skill,
        )
    except ValueError as e:
        return {"error": str(e)}

    ability = _SKILL_ABILITY[skill.lower()]
    rolls, result = _roll_d20(roll_type)
    total = result + modifier
    return {
        "combatant": name,
        "skill": skill,
        "ability": ability,
        "roll_type": roll_type,
        "rolls": rolls,
        "modifier": modifier,
        "total": total,
        "dc": dc,
        "success": total >= dc,
    }


def _exhaustion_level(conditions: list) -> int:
    for c in conditions:
        if isinstance(c, str) and c.startswith("exhaustion-"):
            try:
                return int(c.split("-", 1)[1])
            except ValueError:
                pass
    return 0


async def add_exhaustion(
    db: AsyncSession,
    *,
    character_id: str,
    levels: int = 1,
) -> dict:
    char = await character_queries.get_character(db, uuid.UUID(character_id))
    conditions: list = list(char.conditions or [])
    current = _exhaustion_level(conditions)
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
    current = _exhaustion_level(conditions)
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
        combatant = _find_combatant(state, combatant_id)
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
