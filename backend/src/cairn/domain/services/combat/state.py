import re
import uuid
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from cairn import srd as rules
from cairn.agents import zone_seeder
from cairn.db.models.character import Character
from cairn.db.models.npc import NPC
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import locations as location_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import ConflictError, NotFoundError
from cairn.domain.services import death_mode
from cairn.domain.services.combat import zones as zone_service
from cairn.domain.services.combat.emitter import emit
from cairn.domain.services.combat.rolls import dex_mod, parse_and_roll
from cairn.domain.services.rng import session_rng
from cairn.types import (
    CharacterCombatant,
    Combatant,
    CombatantTeam,
    CombatEffect,
    CombatState,
    MonsterCombatant,
    NpcCombatant,
    TurnEconomy,
)


def _character_combatant(char: Character, initiative_roll: int) -> CharacterCombatant:
    return {
        "id": str(char.id),
        "type": "character",
        "team": "players",
        "ai_controlled": char.is_companion,
        "name": char.name,
        "initiative_roll": initiative_roll,
        "initiative_modifier": char.initiative,
        "zone": None,
        "speed": char.speed,
        "conditions": list(char.conditions),
        "is_alive": char.hp > 0,
        "is_conscious": char.hp > 0,
    }


def _npc_combatant(npc: NPC, team: CombatantTeam, initiative_roll: int) -> NpcCombatant:
    return {
        "id": str(npc.id),
        "type": "npc",
        "team": team,
        "name": npc.name,
        "initiative_roll": initiative_roll,
        "initiative_modifier": npc.initiative,
        "zone": None,
        "speed": npc.speed,
        "conditions": list(npc.conditions),
        "is_alive": npc.hp > 0,
        "is_conscious": npc.hp > 0,
    }


def _monster_combatant(
    monster: dict, *, name: str, team: CombatantTeam, initiative_roll: int, max_hp: int
) -> MonsterCombatant:
    ac = monster["armor_class"][0]["value"] if monster.get("armor_class") else 10
    walk_speed = str((monster.get("speed") or {}).get("walk", "30 ft."))
    match = re.search(r"\d+", walk_speed)
    return {
        "id": f"monster-{uuid.uuid4()}",
        "type": "monster",
        "team": team,
        "name": name,
        "srd_index": monster["index"],
        "initiative_roll": initiative_roll,
        "initiative_modifier": dex_mod(monster.get("dexterity", 10)),
        "zone": None,
        "speed": int(match.group()) if match else 30,
        "hp": max_hp,
        "max_hp": max_hp,
        "ac": ac,
        "conditions": [],
        "is_alive": True,
        "is_conscious": True,
        "actions": monster.get("actions", []),
        "special_abilities": monster.get("special_abilities", []),
    }


async def init_state(
    db: AsyncSession,
    session_id: uuid.UUID,
    enemies: list[dict],
) -> CombatState:
    """Build and persist initial combat state. No ownership check — callers handle auth."""
    db_session = await session_queries.get_session(db, session_id)
    if db_session.combat_active:
        raise ConflictError("combat is already active for this session", code="combat_active")

    rng = session_rng(db_session)
    combatants: list[Combatant] = []

    scene = await scene_queries.get_current_scene(db, db_session.campaign_id)
    location = (
        await location_queries.get_location(db, db_session.current_location_id)
        if db_session.current_location_id is not None
        else None
    )
    generated = await zone_seeder.run(
        location_name=location.name if location else "Unknown location",
        location_description=location.description if location else "",
        scene=dict(scene.authored) if scene else {},
    )
    zone_seed = zone_service.normalize_seed(generated)

    characters = await character_queries.get_party_for_session(db, session_id)
    for char in characters:
        combatants.append(_character_combatant(char, rng.randint(1, 20) + char.initiative))

    for enemy in enemies:
        team = cast(CombatantTeam, enemy.get("team", "enemies"))
        if enemy["type"] == "npc":
            npc = await npc_queries.get_npc(db, uuid.UUID(str(enemy["id"])))
            combatants.append(_npc_combatant(npc, team, rng.randint(1, 20) + npc.initiative))
        elif enemy["type"] == "monster":
            monster = rules.get_monster(enemy["name"])
            if monster is None:
                raise NotFoundError(f"monster '{enemy['name']}' not found in SRD", code="monster_not_found")
            dex = dex_mod(monster.get("dexterity", 10))
            count = max(1, enemy.get("count", 1))
            for i in range(count):
                label = monster["name"] if count == 1 else f"{monster['name']} {i + 1}"
                combatants.append(
                    _monster_combatant(
                        monster,
                        name=label,
                        team="enemies",
                        initiative_roll=rng.randint(1, 20) + dex,
                        max_hp=parse_and_roll(monster["hit_points_roll"], rng),
                    )
                )

    combatants.sort(
        key=lambda c: (c["initiative_roll"], c["initiative_modifier"], rng.random()),
        reverse=True,
    )
    zone_service.place_combatants(combatants, zone_seed)

    turn_economy: dict[str, TurnEconomy] = {
        combatant["id"]: {
            "action_used": False,
            "bonus_action_used": False,
            "reaction_used": False,
            "movement_remaining": combatant["speed"],
        }
        for combatant in combatants
    }

    combat_state: CombatState = {
        "round": 1,
        "turn_index": 0,
        "combatants": combatants,
        "effects": [],
        "zones": zone_seed["zones"],
        "turn_economy": turn_economy,
    }

    await session_queries.update_combat_state(db, session_id, combat_state=combat_state, combat_active=True)
    await emit(db, {"type": "combat_started", "combatant_count": len(combatants)})
    await db.commit()
    return combat_state


async def get_state(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
) -> dict:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    return {"combat_active": db_session.combat_active, "combat_state": db_session.combat_state}


def _is_pc_dead(char: Character) -> bool:
    """A PC who has fully failed death saves or been instant-killed. Pacifist PCs never qualify."""
    return char.hp <= 0 and (char.death_save_failures >= 3 or char.status == "dead")


async def end_state(db: AsyncSession, *, session_id: uuid.UUID) -> None:
    """Clear combat state without ownership check — for tool-facing use.

    Death resolution happens here, at combat end — not per death-save failure.
    """
    session = await session_queries.get_session(db, session_id)
    party = await character_queries.get_party_for_session(db, session_id)
    for char in party:
        if not char.is_companion and _is_pc_dead(char):
            await death_mode.resolve_pc_death(db, session, char)
    await session_queries.update_combat_state(db, session_id, combat_state=None, combat_active=False)
    await db.commit()


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
    end_of_turn_ticks: list[CombatEffect] = []
    expired_effects: list[str] = []
    surviving: list[CombatEffect] = []
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
        e for e in state["effects"] if e["target_id"] == current["id"] and e.get("tick") == "start_of_target_turn"
    ]

    movement = current["speed"]
    economy = state.setdefault("turn_economy", {})
    economy[current["id"]] = {
        "action_used": False,
        "bonus_action_used": False,
        "reaction_used": False,
        "movement_remaining": movement,
    }

    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=True)

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

    await emit(
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
    team_t = cast(CombatantTeam, team)

    if combatant_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(name_or_id))
        entry: Combatant = _character_combatant(char, initiative_roll)
    elif combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(name_or_id))
        entry = _npc_combatant(npc, team_t, initiative_roll)
    elif combatant_type == "monster":
        monster = rules.get_monster(name_or_id)
        if monster is None:
            return {"error": f"Monster '{name_or_id}' not found in SRD."}
        entry = _monster_combatant(
            monster,
            name=monster["name"],
            team=team_t,
            initiative_roll=initiative_roll,
            max_hp=parse_and_roll(monster["hit_points_roll"]),
        )
    else:
        return {"error": f"Unknown combatant_type: {combatant_type!r}"}

    same_team_zone = next((c["zone"] for c in combatants if c["team"] == entry["team"] and c["zone"]), None)
    entry["zone"] = same_team_zone or (state["zones"][0]["id"] if state["zones"] else "open_ground")
    state.setdefault("turn_economy", {})[entry["id"]] = {
        "action_used": False,
        "bonus_action_used": False,
        "reaction_used": False,
        "movement_remaining": entry["speed"],
    }

    insert_idx = next(
        (i for i, c in enumerate(combatants) if initiative_roll > c["initiative_roll"]),
        len(combatants),
    )
    combatants.insert(insert_idx, entry)

    # Keep turn_index pointing at the same combatant after insertion.
    if insert_idx <= state["turn_index"]:
        state["turn_index"] += 1

    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=True)
    await emit(db, {"type": "combatant_added", "name": entry["name"], "initiative": initiative_roll})
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

    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=True)
    await emit(db, {"type": "combatant_removed", "name": removed["name"]})
    await db.commit()
    return {"combatant_removed": True, "combatant": removed["name"]}
