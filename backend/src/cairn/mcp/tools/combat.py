import json
import math
import random
import uuid

import structlog
from langchain_core.tools import tool

from cairn import srd as rules
from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import party_members as party_queries
from cairn.db.queries import sessions as session_queries
from cairn.mcp.tools.dice import _parse_and_roll

log = structlog.get_logger()


def _dex_modifier(monster: dict) -> int:
    return math.floor((monster.get("dexterity", 10) - 10) / 2)


def _find_combatant(state: dict, combatant_id: str) -> dict | None:
    for c in state.get("combatants", []):
        if c["id"] == combatant_id:
            return c
    return None


@tool
async def start_combat(session_id: str, enemies_json: str) -> dict:
    """Initialize a combat encounter. Rolls initiative for all combatants and builds the initiative order.

    enemies_json must be a JSON array. Each entry is either:
    - {"type": "monster", "name": "goblin", "count": 2}  — spawns from SRD stat block
    - {"type": "npc", "id": "<uuid>"}                    — uses a DB NPC record

    Party members are enrolled automatically from the session.

    Args:
        session_id: The session UUID.
        enemies_json: JSON array describing enemies (see format above).
    """  # noqa: E501
    try:
        enemies = json.loads(enemies_json)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid enemies_json: {e}"}

    async with db_client.get_session() as db:
        try:
            session = await session_queries.get_session(db, uuid.UUID(session_id))
            if session.combat_active:
                return {"error": "Combat is already active for this session."}

            combatants: list[dict] = []

            # Enroll party members
            characters = await party_queries.get_party(db, uuid.UUID(session_id))
            for char in characters:
                roll = random.randint(1, 20) + char.initiative
                combatants.append(
                    {
                        "id": str(char.id),
                        "type": "character",
                        "team": "players",
                        "ai_controlled": char.is_companion,
                        "name": char.name,
                        "initiative_roll": roll,
                        "initiative_modifier": char.initiative,
                        "zone": None,
                        "conditions": [],
                        "is_alive": True,
                        "is_conscious": char.hp > 0,
                    }
                )

            # Enroll enemies (and optional ally NPCs via team="players")
            for enemy in enemies:
                team = enemy.get("team", "enemies")
                if enemy["type"] == "npc":
                    npc = await npc_queries.get_npc(db, uuid.UUID(enemy["id"]))
                    roll = random.randint(1, 20) + npc.initiative
                    combatants.append(
                        {
                            "id": str(npc.id),
                            "type": "npc",
                            "team": team,
                            "name": npc.name,
                            "initiative_roll": roll,
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
                        return {"error": f"Monster '{enemy['name']}' not found in SRD."}

                    dex_mod = _dex_modifier(monster)
                    ac = monster["armor_class"][0]["value"] if monster.get("armor_class") else 10
                    count = max(1, enemy.get("count", 1))

                    for i in range(count):
                        _, max_hp = _parse_and_roll(monster["hit_points_roll"])
                        roll = random.randint(1, 20) + dex_mod
                        label = monster["name"] if count == 1 else f"{monster['name']} {i + 1}"
                        combatants.append(
                            {
                                "id": f"monster-{uuid.uuid4()}",
                                "type": "monster",
                                "team": "enemies",
                                "name": label,
                                "srd_index": monster["index"],
                                "initiative_roll": roll,
                                "initiative_modifier": dex_mod,
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

            # Sort by initiative (ties broken by modifier, then random)
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
                db, uuid.UUID(session_id), combat_state=combat_state, combat_active=True
            )
            await db.commit()

            return {"combat_started": True, "combat_state": combat_state}
        except Exception as exc:
            log.error("start_combat_error", session_id=session_id, error=str(exc))
            return {"error": str(exc)}


@tool
async def end_combat(session_id: str, outcome: str) -> dict:
    """End the current combat encounter and clear combat state.

    Args:
        session_id: The session UUID.
        outcome: One of "victory", "defeat", "retreat", or "resolved" (peaceful end).
    """
    async with db_client.get_session() as db:
        await session_queries.update_combat_state(
            db, uuid.UUID(session_id), combat_state=None, combat_active=False
        )
        await db.commit()
        return {"combat_ended": True, "outcome": outcome}


@tool
async def apply_damage(
    session_id: str,
    combatant_id: str,
    combatant_type: str,
    amount: int,
    damage_type: str = "untyped",
) -> dict:
    """Apply damage to a combatant, respecting temp HP and checking for unconscious/death.

    combatant_type must be "character", "npc", or "monster".
    Monsters (SRD-spawned) have their HP tracked in combat_state.
    Characters and NPCs have their HP persisted to their DB record.

    Args:
        session_id: The session UUID.
        combatant_id: The combatant's ID (UUID for character/npc, or the monster's generated id).
        combatant_type: "character", "npc", or "monster".
        amount: Raw damage amount (before temp HP absorption). Must be >= 0.
        damage_type: Damage type for narrative purposes (e.g. "fire", "slashing", "necrotic").
    """
    async with db_client.get_session() as db:
        if combatant_type == "character":
            char = await character_queries.get_character(db, uuid.UUID(combatant_id))
            effective = max(0, amount - char.temp_hp)
            char.temp_hp = max(0, char.temp_hp - amount)
            char.hp = max(0, char.hp - effective)
            is_unconscious = char.hp == 0
            new_hp = char.hp
            await db.commit()
            return {
                "combatant": char.name,
                "damage_taken": effective,
                "temp_hp_absorbed": amount - effective,
                "hp": new_hp,
                "is_unconscious": is_unconscious,
                "is_dead": False,
            }

        elif combatant_type == "npc":
            npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
            effective = max(0, amount - npc.temp_hp)
            npc.temp_hp = max(0, npc.temp_hp - amount)
            npc.hp = max(0, npc.hp - effective)
            is_dead = npc.hp == 0
            new_hp = npc.hp
            await db.commit()
            return {
                "combatant": npc.name,
                "damage_taken": effective,
                "temp_hp_absorbed": amount - effective,
                "hp": new_hp,
                "is_unconscious": is_dead,
                "is_dead": is_dead,
            }

        elif combatant_type == "monster":
            session = await session_queries.get_session(db, uuid.UUID(session_id))
            state = session.combat_state or {}
            combatant = _find_combatant(state, combatant_id)
            if combatant is None:
                return {"error": f"Monster '{combatant_id}' not found in combat state."}

            effective = max(0, amount - combatant.get("temp_hp", 0))
            combatant["hp"] = max(0, combatant["hp"] - effective)
            combatant["is_alive"] = combatant["hp"] > 0
            combatant["is_conscious"] = combatant["is_alive"]

            await session_queries.update_combat_state(
                db,
                uuid.UUID(session_id),
                combat_state=state,
                combat_active=session.combat_active,
            )
            await db.commit()
            return {
                "combatant": combatant["name"],
                "damage_taken": effective,
                "hp": combatant["hp"],
                "is_alive": combatant["is_alive"],
                "is_dead": not combatant["is_alive"],
            }

        else:
            return {"error": f"Unknown combatant_type '{combatant_type}'."}


@tool
async def apply_healing(
    session_id: str,
    combatant_id: str,
    combatant_type: str,
    amount: int,
) -> dict:
    """Heal a combatant by amount, not exceeding their max HP. Clears unconscious status if HP > 0.

    Args:
        session_id: The session UUID.
        combatant_id: The combatant's UUID or monster id.
        combatant_type: "character", "npc", or "monster".
        amount: HP to restore.
    """
    async with db_client.get_session() as db:
        if combatant_type == "character":
            char = await character_queries.get_character(db, uuid.UUID(combatant_id))
            char.hp = min(char.max_hp, char.hp + amount)
            if char.hp > 0:
                char.death_save_successes = 0
                char.death_save_failures = 0
            await db.commit()
            return {
                "combatant": char.name,
                "hp": char.hp,
                "max_hp": char.max_hp,
                "is_conscious": char.hp > 0,
            }

        elif combatant_type == "npc":
            npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
            npc.hp = min(npc.max_hp, npc.hp + amount)
            await db.commit()
            return {"combatant": npc.name, "hp": npc.hp, "max_hp": npc.max_hp}

        elif combatant_type == "monster":
            session = await session_queries.get_session(db, uuid.UUID(session_id))
            state = session.combat_state or {}
            combatant = _find_combatant(state, combatant_id)
            if combatant is None:
                return {"error": f"Monster '{combatant_id}' not found in combat state."}
            combatant["hp"] = min(combatant["max_hp"], combatant["hp"] + amount)
            combatant["is_alive"] = True
            combatant["is_conscious"] = True
            await session_queries.update_combat_state(
                db,
                uuid.UUID(session_id),
                combat_state=state,
                combat_active=session.combat_active,
            )
            await db.commit()
            return {
                "combatant": combatant["name"],
                "hp": combatant["hp"],
                "max_hp": combatant["max_hp"],
            }

        else:
            return {"error": f"Unknown combatant_type '{combatant_type}'."}


@tool
async def apply_condition(
    session_id: str,
    combatant_id: str,
    combatant_type: str,
    condition: str,
) -> dict:
    """Apply a condition to a combatant (e.g. "poisoned", "blinded", "prone", "stunned").

    For characters, conditions are tracked in combat_state (transient).
    For NPCs, conditions are also tracked in combat_state for the encounter.
    For monsters, conditions live in combat_state.

    Args:
        session_id: The session UUID.
        combatant_id: The combatant's UUID or monster id.
        combatant_type: "character", "npc", or "monster".
        condition: The condition name.
    """
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        state = session.combat_state or {}
        combatant = _find_combatant(state, combatant_id)

        if combatant is None:
            return {"error": f"Combatant '{combatant_id}' not found in combat state."}

        conditions = combatant.setdefault("conditions", [])
        if condition not in conditions:
            conditions.append(condition)

        await session_queries.update_combat_state(
            db, uuid.UUID(session_id), combat_state=state, combat_active=session.combat_active
        )
        await db.commit()
        return {"combatant": combatant["name"], "conditions": conditions}


@tool
async def remove_condition(
    session_id: str,
    combatant_id: str,
    combatant_type: str,
    condition: str,
) -> dict:
    """Remove a condition from a combatant.

    Args:
        session_id: The session UUID.
        combatant_id: The combatant's UUID or monster id.
        combatant_type: "character", "npc", or "monster".
        condition: The condition to remove.
    """
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        state = session.combat_state or {}
        combatant = _find_combatant(state, combatant_id)

        if combatant is None:
            return {"error": f"Combatant '{combatant_id}' not found in combat state."}

        conditions = combatant.get("conditions", [])
        combatant["conditions"] = [c for c in conditions if c != condition]

        await session_queries.update_combat_state(
            db, uuid.UUID(session_id), combat_state=state, combat_active=session.combat_active
        )
        await db.commit()
        return {"combatant": combatant["name"], "conditions": combatant["conditions"]}


@tool
async def roll_death_save(session_id: str, character_id: str) -> dict:
    """Roll a death saving throw for an unconscious character at 0 HP.

    D&D rules: roll d20, DC 10.
    - Natural 20: regain 1 HP (stabilized).
    - Natural 1: counts as 2 failures.
    - 3 successes: stable (no longer making saves).
    - 3 failures: dead.

    Only valid for player characters — NPCs and monsters die immediately at 0 HP.

    Args:
        session_id: The session UUID.
        character_id: The character's UUID.
    """
    async with db_client.get_session() as db:
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

        await db.commit()

        return {
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


@tool
async def advance_turn(session_id: str) -> dict:
    """Advance to the next combatant's turn in the initiative order, skipping dead combatants.
    Increments the round counter when the initiative order wraps around.

    Also ticks multi-round effects:
    - end_of_turn_ticks: effects that trigger at end of the OUTGOING combatant's turn (e.g. Hold Person save). Resolve these before the next combatant acts.
    - start_of_turn_ticks: effects that trigger at start of the INCOMING combatant's turn (e.g. poison damage). Resolve these before the combatant takes their action.
    - expired_effects: effects whose duration ran out this turn (already removed from state).

    Args:
        session_id: The session UUID.
    """  # noqa: E501
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        if not session.combat_active or not session.combat_state:
            return {"error": "No active combat."}

        state = session.combat_state
        combatants = state["combatants"]
        alive = [c for c in combatants if c.get("is_alive", True)]

        if not alive:
            return {"error": "No living combatants remain."}

        outgoing = combatants[state["turn_index"]]

        # --- End-of-turn effect processing for outgoing combatant ---
        effects = state.setdefault("effects", [])
        end_of_turn_ticks = []
        expired_effects = []
        surviving = []
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

        # --- Advance turn ---
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

        # --- Start-of-turn effect processing for incoming combatant ---
        start_of_turn_ticks = [
            e
            for e in state["effects"]
            if e["target_id"] == current["id"] and e.get("tick") == "start_of_target_turn"
        ]

        # --- Reset action economy ---
        economy = state.setdefault("turn_economy", {})
        economy[current["id"]] = {
            "action_used": False,
            "bonus_action_used": False,
            "reaction_used": False,
            "movement_remaining": current.get("speed", 30),
        }

        await session_queries.update_combat_state(
            db, uuid.UUID(session_id), combat_state=state, combat_active=True
        )
        await db.commit()

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
        return result


@tool
async def apply_effect(
    session_id: str,
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
    """Track a multi-round effect on a combatant (concentration spell, poison, regeneration, etc.).

    tick values:
      "start_of_target_turn" — triggers at start of target's turn (poison damage, regen)
      "end_of_target_turn"   — triggers at end of target's turn (Hold Person save, Slow save)
      ""                     — passive, no tick (Bless, Haste — just needs to be visible in state)

    advance_turn will return end_of_turn_ticks / start_of_turn_ticks so you know when to resolve.
    Call remove_effect when: concentration breaks, dispel magic succeeds, or a save ends the effect.

    Args:
        session_id: The session UUID.
        target_id: Combatant ID the effect applies to.
        effect_name: Human-readable name, e.g. "Hold Person", "Bless", "Poison".
        duration_rounds: How many rounds the effect lasts before expiring automatically.
        tick: When the effect triggers each round. "" for passive effects.
        save_ability: Ability for the repeating save, e.g. "wis". Empty if no repeating save.
        save_dc: DC for the repeating save. 0 if no save.
        condition: Condition applied by this effect, e.g. "paralyzed". Empty if none.
        damage: Tick damage dice expression, e.g. "1d6". Empty if no tick damage.
        damage_type: Damage type for tick damage, e.g. "poison".
        mechanical_notes: Free-text notes for how to resolve ticks, e.g. "On save success, effect ends and condition is removed."
        source_id: Combatant ID of the caster or source. Optional.
    """  # noqa: E501
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
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
            db, uuid.UUID(session_id), combat_state=state, combat_active=session.combat_active
        )
        await db.commit()
        return {"effect_applied": True, "effect": effect}


@tool
async def remove_effect(session_id: str, effect_id: str) -> dict:
    """Remove an active effect by its ID.

    Call this when: concentration breaks, dispel magic succeeds, or a repeating save ends the effect.

    Args:
        session_id: The session UUID.
        effect_id: The effect's UUID (from the apply_effect response).
    """  # noqa: E501
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        state = session.combat_state or {}
        effects = state.get("effects", [])
        removed = next((e for e in effects if e["id"] == effect_id), None)
        if removed is None:
            return {"error": f"Effect '{effect_id}' not found."}
        state["effects"] = [e for e in effects if e["id"] != effect_id]
        await session_queries.update_combat_state(
            db, uuid.UUID(session_id), combat_state=state, combat_active=session.combat_active
        )
        await db.commit()
        return {"effect_removed": True, "effect_name": removed["name"]}
