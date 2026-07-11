import math
import random
import re
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from cairn import srd as rules
from cairn.application.combat.emitter import emit
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.combat_rules import (
    ABILITY_LONG,
    SKILL_ABILITY,
    empty_combat_state,
    find_combatant,
    find_monster,
    get_ability_score,
)
from cairn.domain.services.rng import session_rng

# A Random | None — when None, fall back to the module-level random (non-deterministic).
type Rng = random.Random | None


@dataclass(frozen=True)
class AttackRoll:
    rolls: tuple[int, ...]
    natural: int
    modifier: int
    total: int
    target_ac: int
    cover_bonus: int
    hit: bool
    critical: bool


def roll_attack(
    *,
    to_hit_bonus: int,
    target_ac: int,
    cover_ac_bonus: int = 0,
    advantage: bool = False,
    disadvantage: bool = False,
    rng: Rng = None,
) -> AttackRoll:
    """Resolve one authoritative attack roll, including hard cover AC."""
    roll_type = "normal"
    if advantage != disadvantage:
        roll_type = "advantage" if advantage else "disadvantage"
    rolled, natural = roll_d20(roll_type, rng)
    effective_ac = target_ac + max(0, cover_ac_bonus)
    total = natural + to_hit_bonus
    hit = natural == 20 or (natural != 1 and total >= effective_ac)
    return AttackRoll(
        rolls=tuple(rolled),
        natural=natural,
        modifier=to_hit_bonus,
        total=total,
        target_ac=effective_ac,
        cover_bonus=max(0, cover_ac_bonus),
        hit=hit,
        critical=natural == 20,
    )


def _roll_die(sides: int, rng: Rng = None) -> int:
    return (rng or random).randint(1, sides)


def parse_and_roll(expression: str, rng: Rng = None) -> int:
    match = re.fullmatch(r"(\d+)d(\d+)([+-]\d+)?", expression.strip())
    if not match:
        raise ValueError(f"Invalid dice expression: {expression!r}")
    count, sides = int(match.group(1)), int(match.group(2))
    modifier = int(match.group(3) or 0)
    return sum(_roll_die(sides, rng) for _ in range(count)) + modifier


def mod(score: int) -> int:
    return math.floor((score - 10) / 2)


def dex_mod(score: int) -> int:
    return mod(score)


def roll_d20(roll_type: str, rng: Rng = None) -> tuple[list[int], int]:
    if roll_type == "advantage":
        r1, r2 = _roll_die(20, rng), _roll_die(20, rng)
        return [r1, r2], max(r1, r2)
    if roll_type == "disadvantage":
        r1, r2 = _roll_die(20, rng), _roll_die(20, rng)
        return [r1, r2], min(r1, r2)
    r = _roll_die(20, rng)
    return [r], r


async def _rng_for(db: AsyncSession, session_id: uuid.UUID) -> random.Random:
    """Build the session-seeded RNG for a combat roll."""
    session = await session_queries.get_session(db, session_id)
    return session_rng(session)


async def roll_death_save(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    character_id: str,
) -> dict:
    char = await character_queries.get_character(db, uuid.UUID(character_id))
    if char.hp > 0:
        return {"error": f"{char.name} is not at 0 HP and doesn't need a death save."}

    rng = await _rng_for(db, session_id)
    roll = rng.randint(1, 20)
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
    await emit(db, {"type": "death_save_rolled", **result})
    return result


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
        name, modifier = await save_modifier(
            db,
            session_id=session_id,
            combatant_id=combatant_id,
            combatant_type=combatant_type,
            ability=ability,
        )
    except ValueError as e:
        return {"error": str(e)}

    rolls, result = roll_d20(roll_type, await _rng_for(db, session_id))
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


async def save_modifier(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    combatant_type: str,
    ability: str,
) -> tuple[str, int]:
    """Return (name, save_modifier) for a combatant. Shared by roll_saving_throw and apply_aoe_damage."""
    if combatant_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(combatant_id))
        modifier = mod(get_ability_score(char.ability_scores, ability))
        if f"saving-throw-{ability}" in (char.saving_throw_proficiencies or []):
            modifier += char.proficiency_bonus
        return char.name, modifier

    if combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
        modifier = mod(get_ability_score(npc.ability_scores, ability))
        if f"saving-throw-{ability}" in (npc.saving_throw_proficiencies or []):
            modifier += npc.proficiency_bonus
        return npc.name, modifier

    if combatant_type == "monster":
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or empty_combat_state()
        combatant = find_monster(state, combatant_id)
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
        modifier = prof_entry["value"] if prof_entry else mod(monster_data.get(ABILITY_LONG[ability], 10))
        return combatant["name"], modifier

    raise ValueError(f"Unknown combatant_type: {combatant_type!r}")


async def skill_modifier(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    combatant_type: str,
    skill: str,
) -> tuple[str, int]:
    """Return (name, skill_modifier) for a combatant. Shared by roll_skill_check and resolve_contest."""
    skill_key = skill.lower()
    ability = SKILL_ABILITY.get(skill_key)
    if ability is None:
        raise ValueError(f"Unknown skill: {skill!r}")

    if combatant_type == "character":
        char = await character_queries.get_character(db, uuid.UUID(combatant_id))
        modifier = mod(get_ability_score(char.ability_scores, ability))
        if any(s.lower() == skill_key for s in (char.skill_proficiencies or [])):
            modifier += char.proficiency_bonus
        return char.name, modifier

    if combatant_type == "npc":
        npc = await npc_queries.get_npc(db, uuid.UUID(combatant_id))
        modifier = mod(get_ability_score(npc.ability_scores, ability))
        if any(s.lower() == skill_key for s in (npc.skill_proficiencies or [])):
            modifier += npc.proficiency_bonus
        return npc.name, modifier

    if combatant_type == "monster":
        session = await session_queries.get_session(db, session_id)
        state = session.combat_state or empty_combat_state()
        combatant = find_monster(state, combatant_id)
        if combatant is None:
            raise ValueError(f"Monster '{combatant_id}' not found in combat state.")
        monster_data = rules.get_monster(combatant["srd_index"])
        if monster_data is None:
            raise ValueError(f"Monster SRD data not found for '{combatant['srd_index']}'.")
        skill_index = f"skill-{skill_key.replace(' ', '-')}"
        prof_entry = next(
            (p for p in monster_data.get("proficiencies", []) if p["proficiency"]["index"] == skill_index),
            None,
        )
        modifier = prof_entry["value"] if prof_entry is not None else mod(monster_data.get(ABILITY_LONG[ability], 10))
        return combatant["name"], modifier

    raise ValueError(f"Unknown combatant_type: {combatant_type!r}")


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
    if skill.lower() not in SKILL_ABILITY:
        return {"error": f"Unknown skill: {skill!r}. Valid skills: {sorted(SKILL_ABILITY)}"}
    try:
        name, modifier = await skill_modifier(
            db,
            session_id=session_id,
            combatant_id=combatant_id,
            combatant_type=combatant_type,
            skill=skill,
        )
    except ValueError as e:
        return {"error": str(e)}

    ability = SKILL_ABILITY[skill.lower()]
    rolls, result = roll_d20(roll_type, await _rng_for(db, session_id))
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
        state = session.combat_state or empty_combat_state()
        combatant = find_combatant(state, combatant_id)
        if combatant is not None:
            modifier = combatant["initiative_modifier"]
            name = combatant["name"]
        else:
            monster_data = rules.get_monster(combatant_id)
            if monster_data is None:
                return {"error": f"Monster '{combatant_id}' not found in combat state or SRD."}
            modifier = dex_mod(monster_data.get("dexterity", 10))
            name = monster_data["name"]

    else:
        return {"error": f"Unknown combatant_type: {combatant_type!r}"}

    rolls, result = roll_d20(roll_type, await _rng_for(db, session_id))
    total = result + modifier
    return {
        "combatant": name,
        "roll_type": roll_type,
        "rolls": rolls,
        "modifier": modifier,
        "initiative": total,
    }


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
        attacker_name, atk_mod = await skill_modifier(
            db,
            session_id=session_id,
            combatant_id=attacker_id,
            combatant_type=attacker_type,
            skill=attacker_skill,
        )
        defender_name, def_mod = await skill_modifier(
            db,
            session_id=session_id,
            combatant_id=defender_id,
            combatant_type=defender_type,
            skill=defender_skill,
        )
    except ValueError as e:
        return {"error": str(e)}

    rng = await _rng_for(db, session_id)
    atk_rolls, atk_result = roll_d20("normal", rng)
    def_rolls, def_result = roll_d20("normal", rng)
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
