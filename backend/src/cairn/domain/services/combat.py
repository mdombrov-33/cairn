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


def _roll_die(sides: int) -> int:
    return random.randint(1, sides)


def _parse_and_roll(expression: str) -> int:
    match = re.fullmatch(r"(\d+)d(\d+)([+-]\d+)?", expression.strip())
    if not match:
        raise ValueError(f"Invalid dice expression: {expression!r}")
    count, sides = int(match.group(1)), int(match.group(2))
    modifier = int(match.group(3) or 0)
    return sum(_roll_die(sides) for _ in range(count)) + modifier


def _dex_mod(score: int) -> int:
    return math.floor((score - 10) / 2)


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
