"""Tactical-zone invariants for theater-of-mind combat."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn import srd as rules
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.services.combat.emitter import emit
from cairn.domain.services.combat.helpers import find_combatant, get_ability_score
from cairn.domain.services.combat.rolls import mod, parse_and_roll
from cairn.domain.services.rng import session_rng
from cairn.types import Combatant, CombatState, CombatZone, InventoryItem, ZoneSeed

OPEN_GROUND: CombatZone = {
    "id": "open_ground",
    "name": "Open Ground",
    "description": "An open area with no meaningful tactical divisions.",
    "cover": "none",
    "cover_ac_bonus": 0,
    "cover_save_bonus": 0,
    "difficult_terrain": False,
    "hazard": None,
    "distances": {},
}


def fallback_seed() -> ZoneSeed:
    return {"zones": [OPEN_GROUND.copy()], "player_start": "open_ground", "enemy_start": "open_ground"}


def normalize_seed(seed: ZoneSeed | None) -> ZoneSeed:
    """Reject unusable model output as a whole; combat falls back instead of partially seeding."""
    if seed is None:
        return fallback_seed()
    zone_ids = {zone["id"] for zone in seed["zones"]}
    if len(zone_ids) != len(seed["zones"]):
        return fallback_seed()
    if seed["player_start"] not in zone_ids or seed["enemy_start"] not in zone_ids:
        return fallback_seed()
    if any(target not in zone_ids for zone in seed["zones"] for target in zone["distances"]):
        return fallback_seed()
    return seed


def place_combatants(combatants: list[Combatant], seed: ZoneSeed) -> None:
    """Apply the seeder's per-team placement to every combatant."""
    for combatant in combatants:
        combatant["zone"] = seed["player_start"] if combatant["team"] == "players" else seed["enemy_start"]


def _damage_expression(dice: str, modifier: int) -> str:
    if modifier == 0:
        return dice
    return f"{dice}{modifier:+d}"


async def _melee_attack(db: AsyncSession, combatant: Combatant) -> dict | None:
    """Return the combatant's first usable melee weapon in a uniform shape."""
    if combatant["type"] == "monster":
        action = next(
            (item for item in combatant.get("actions", []) if item.get("desc", "").startswith("Melee Weapon Attack")),
            None,
        )
        if action is None or not action.get("damage"):
            return None
        damage = action["damage"][0]
        return {
            "name": action["name"],
            "attack_bonus": action.get("attack_bonus", 0),
            "damage_dice": damage["damage_dice"],
            "damage_type": damage["damage_type"]["index"],
        }

    entity = (
        await character_queries.get_character(db, uuid.UUID(combatant["id"]))
        if combatant["type"] == "character"
        else await npc_queries.get_npc(db, uuid.UUID(combatant["id"]))
    )
    candidates: list[tuple[InventoryItem, dict]] = []
    for item in entity.inventory or []:
        weapon = rules.get_weapon(item.get("srd_index") or item["name"])
        if weapon is not None and weapon.get("weapon_range") == "Melee":
            candidates.append((item, weapon))
    if not candidates:
        return None
    _, weapon = next((pair for pair in candidates if pair[0].get("equipped")), candidates[0])
    properties = {item.get("index") for item in weapon.get("properties", [])}
    strength = mod(get_ability_score(entity.ability_scores, "str"))
    dexterity = mod(get_ability_score(entity.ability_scores, "dex"))
    ability_modifier = max(strength, dexterity) if "finesse" in properties else strength
    damage = weapon["damage"]
    return {
        "name": weapon["name"],
        "attack_bonus": ability_modifier + entity.proficiency_bonus,
        "damage_dice": _damage_expression(damage["damage_dice"], ability_modifier),
        "damage_type": damage["damage_type"]["index"],
    }


async def _armor_class(db: AsyncSession, combatant: Combatant) -> int:
    if combatant["type"] == "monster":
        return combatant["ac"]
    if combatant["type"] == "character":
        return (await character_queries.get_character(db, uuid.UUID(combatant["id"]))).ac
    return (await npc_queries.get_npc(db, uuid.UUID(combatant["id"]))).ac


async def _opportunity_attacks(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    mover: Combatant,
    state: CombatState,
) -> list[dict]:
    """Resolve automatic melee opportunity attacks before the mover exits its current zone."""
    from cairn.domain.services.combat import mutations

    session = await session_queries.get_session(db, session_id)
    rng = session_rng(session)
    economy = state.setdefault("turn_economy", {})
    results: list[dict] = []
    for attacker in state["combatants"]:
        if (
            attacker["id"] == mover["id"]
            or attacker["team"] == mover["team"]
            or attacker["zone"] != mover["zone"]
            or not attacker["is_alive"]
            or not attacker["is_conscious"]
        ):
            continue
        entry = economy.setdefault(
            attacker["id"],
            {
                "action_used": False,
                "bonus_action_used": False,
                "reaction_used": False,
                "movement_remaining": attacker["speed"],
            },
        )
        if entry["reaction_used"]:
            continue
        attack = await _melee_attack(db, attacker)
        if attack is None:
            continue

        entry["reaction_used"] = True
        attack_roll = rng.randint(1, 20)
        attack_total = attack_roll + attack["attack_bonus"]
        hit = attack_roll == 20 or (attack_roll != 1 and attack_total >= await _armor_class(db, mover))
        damage = parse_and_roll(attack["damage_dice"], rng) if hit else 0
        if hit:
            await mutations.apply_damage(
                db,
                session_id=session_id,
                combatant_id=mover["id"],
                combatant_type=mover["type"],
                amount=damage,
                damage_type=attack["damage_type"],
            )
        result = {
            "attacker_id": attacker["id"],
            "attacker": attacker["name"],
            "attack": attack["name"],
            "attack_roll": attack_roll,
            "attack_total": attack_total,
            "hit": hit,
            "damage": damage,
        }
        results.append(result)
        await emit(db, {"type": "opportunity_attack", "target_id": mover["id"], **result})
    return results


async def move_combatant(db: AsyncSession, *, session_id: uuid.UUID, combatant_id: str, target_zone_id: str) -> dict:
    """Move one combatant across a reachable zone edge, spending its real movement budget."""
    session = await session_queries.get_session(db, session_id)
    if not session.combat_active or not session.combat_state:
        return {"error": "No active combat."}

    state = session.combat_state
    combatant = find_combatant(state, combatant_id)
    if combatant is None:
        return {"error": f"Combatant '{combatant_id}' not found."}
    by_id = {zone["id"]: zone for zone in state["zones"]}
    target = by_id.get(target_zone_id)
    if target is None:
        return {"error": f"Zone '{target_zone_id}' not found."}
    current = by_id.get(combatant["zone"] or "")
    if current is None:
        return {"error": f"{combatant['name']} has no valid current zone."}
    if target_zone_id == current["id"]:
        return {"error": f"{combatant['name']} is already in {target['name']}."}

    distance = current["distances"].get(target_zone_id)
    if distance is None:
        return {"error": f"{target['name']} is not reachable from {current['name']}."}
    blocked = {condition.lower() for condition in combatant["conditions"]} & {"grappled", "restrained"}
    if blocked:
        return {"error": f"{combatant['name']} cannot move while {sorted(blocked)[0]}."}

    cost = 30 if distance == "close" else 60
    if target["difficult_terrain"]:
        cost *= 2
    economy = state.setdefault("turn_economy", {})
    entry = economy.setdefault(
        combatant_id,
        {
            "action_used": False,
            "bonus_action_used": False,
            "reaction_used": False,
            "movement_remaining": combatant["speed"],
        },
    )
    remaining = entry["movement_remaining"]
    if cost > remaining:
        return {"error": f"{target['name']} costs {cost}ft; only {remaining}ft of movement remains."}

    opportunity_attacks = await _opportunity_attacks(db, session_id=session_id, mover=combatant, state=state)
    combatant["zone"] = target_zone_id
    entry["movement_remaining"] = remaining - cost
    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=True)
    result = {
        "combatant_id": combatant_id,
        "combatant": combatant["name"],
        "from_zone": current["id"],
        "to_zone": target_zone_id,
        "movement_spent": cost,
        "movement_remaining": entry["movement_remaining"],
        "opportunity_attacks": opportunity_attacks,
    }
    await emit(db, {"type": "combatant_moved", **result})
    await db.commit()
    return result


async def combatants_in_zone(db: AsyncSession, *, session_id: uuid.UUID, zone_id: str) -> dict:
    session = await session_queries.get_session(db, session_id)
    if not session.combat_active or not session.combat_state:
        return {"error": "No active combat."}
    if zone_id not in {zone["id"] for zone in session.combat_state["zones"]}:
        return {"error": f"Zone '{zone_id}' not found."}
    return {
        "zone_id": zone_id,
        "combatants": [item for item in session.combat_state["combatants"] if item["zone"] == zone_id],
    }


async def zones_in_range(db: AsyncSession, *, session_id: uuid.UUID, from_zone_id: str, range_category: str) -> dict:
    session = await session_queries.get_session(db, session_id)
    if not session.combat_active or not session.combat_state:
        return {"error": "No active combat."}
    by_id = {zone["id"]: zone for zone in session.combat_state["zones"]}
    origin = by_id.get(from_zone_id)
    if origin is None:
        return {"error": f"Zone '{from_zone_id}' not found."}
    if range_category not in {"close", "far"}:
        return {"error": "range_category must be 'close' or 'far'."}
    return {
        "from_zone": from_zone_id,
        "range_category": range_category,
        "zones": [
            by_id[zone_id]
            for zone_id, distance in origin["distances"].items()
            if distance == range_category and zone_id in by_id
        ],
    }
