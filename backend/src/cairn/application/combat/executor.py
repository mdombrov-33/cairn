"""Deterministic, interruptible execution of typed combat plans."""

import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from cairn import srd as rules
from cairn.application.combat import mutations, zones
from cairn.application.combat import state as state_service
from cairn.application.combat.plan import (
    AdvanceTurnOperation,
    ApplyConditionOperation,
    AttackOperation,
    CastOperation,
    CombatOperation,
    CombatPlan,
    EndCombatOperation,
    MoveOperation,
    ReadyOperation,
)
from cairn.application.combat.reactions import ReactionOpportunity, matches_readied, recommendation, should_react
from cairn.application.combat.rolls import AttackRoll, mod, parse_and_roll, roll_attack, roll_saving_throw
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.combat import Combatant, CombatState, PendingReaction, ReactionName, TurnEconomy
from cairn.domain.combat_range import range_feet_to_category, target_in_range
from cairn.domain.combat_rules import find_combatant, get_ability_score
from cairn.domain.exceptions import ConflictError, ValidationError
from cairn.domain.services.rng import session_rng
from cairn.domain.services.settings import ReactionControl, resolve_settings
from cairn.srd.catalog import catalog

REACTION_COUNTDOWN_SECONDS = 20


@dataclass(frozen=True)
class ExecutionComplete:
    facts: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionSuspended:
    prompt: PendingReaction


ExecutionOutcome = ExecutionComplete | ExecutionSuspended


def reaction_prompt_data(prompt: PendingReaction) -> dict[str, Any]:
    return {
        "checkpoint_id": prompt["checkpoint_id"],
        "trigger": prompt["trigger"],
        "description": prompt["description"],
        "options": prompt["options"],
        "recommendation": prompt["recommendation"],
        "countdown_seconds": REACTION_COUNTDOWN_SECONDS,
    }


def _economy(state: CombatState, combatant_id: str, speed: int) -> TurnEconomy:
    return state.setdefault("turn_economy", {}).setdefault(
        combatant_id,
        {
            "action_used": False,
            "bonus_action_used": False,
            "reaction_used": False,
            "movement_remaining": speed,
        },
    )


async def _hp(db: AsyncSession, combatant: dict[str, Any]) -> int:
    if combatant["type"] == "monster":
        return int(combatant["hp"])
    if combatant["type"] == "character":
        return (await character_queries.get_character(db, uuid.UUID(combatant["id"]))).hp
    return (await npc_queries.get_npc(db, uuid.UUID(combatant["id"]))).hp


async def _has_reaction_spell(db: AsyncSession, combatant: dict[str, Any], spell_name: str, minimum_slot: int) -> bool:
    if combatant["type"] == "monster":
        return False
    entity = (
        await character_queries.get_character(db, uuid.UUID(combatant["id"]))
        if combatant["type"] == "character"
        else await npc_queries.get_npc(db, uuid.UUID(combatant["id"]))
    )
    known = {name.casefold() for name in entity.spells_known or []}
    prepared = {name.casefold() for name in getattr(entity, "prepared_spells", []) or []}
    has_spell = spell_name.casefold() in known | prepared
    return has_spell and any(
        int(level) >= minimum_slot and count > 0 for level, count in (entity.spell_slots or {}).items()
    )


async def _spend_spell_slot(db: AsyncSession, combatant: dict[str, Any], minimum_level: int) -> int:
    if combatant["type"] == "monster":
        raise ValidationError("monster reaction spell resources are unavailable", code="reaction_unavailable")
    entity = (
        await character_queries.get_character(db, uuid.UUID(combatant["id"]))
        if combatant["type"] == "character"
        else await npc_queries.get_npc(db, uuid.UUID(combatant["id"]))
    )
    slots = dict(entity.spell_slots or {})
    level = next((level for level in sorted(map(int, slots)) if level >= minimum_level and slots[str(level)] > 0), None)
    if level is None:
        raise ValidationError("no eligible spell slot remains", code="reaction_unavailable")
    slots[str(level)] -= 1
    entity.spell_slots = slots
    await db.flush()
    return level


async def _spell_entity(db: AsyncSession, combatant: Combatant) -> Any:
    if combatant["type"] == "character":
        return await character_queries.get_character(db, uuid.UUID(combatant["id"]))
    if combatant["type"] == "npc":
        return await npc_queries.get_npc(db, uuid.UUID(combatant["id"]))
    return None


async def _spend_exact_slot(db: AsyncSession, combatant: Combatant, level: int) -> None:
    if level == 0:
        return
    entity = await _spell_entity(db, combatant)
    if entity is None:
        raise ValidationError("monster spell resources are unavailable", code="unsupported_spell")
    slots = dict(entity.spell_slots or {})
    if slots.get(str(level), 0) <= 0:
        raise ValidationError(f"no level {level} spell slot remains", code="resource_unavailable")
    slots[str(level)] -= 1
    entity.spell_slots = slots
    await db.flush()


async def _can_cast(db: AsyncSession, combatant: Combatant, spell_name: str) -> bool:
    entity = await _spell_entity(db, combatant)
    if entity is None:
        if combatant["type"] != "monster":
            return False
        return any(spell_name.casefold() in str(action).casefold() for action in combatant.get("actions", []))
    known = {name.casefold() for name in entity.spells_known or []}
    prepared = {name.casefold() for name in getattr(entity, "prepared_spells", []) or []}
    return spell_name.casefold() in known | prepared


async def _spell_save_dc(db: AsyncSession, caster: Combatant) -> int:
    entity = await _spell_entity(db, caster)
    if entity is None:
        return 10
    ability = entity.spellcasting_ability or "int"
    return 8 + entity.proficiency_bonus + mod(get_ability_score(entity.ability_scores, ability))


def _cover_bonus(state: CombatState, target: Combatant) -> int:
    zone = next((zone for zone in state["zones"] if zone["id"] == target.get("zone")), None)
    return int(zone["cover_ac_bonus"]) if zone is not None else 0


async def _make_checkpoint(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    state: CombatState,
    plan: CombatPlan,
    cursor: int,
    facts: list[str],
    name: ReactionName,
    trigger: str,
    description: str,
    opportunity: ReactionOpportunity,
    frame: dict[str, Any],
    depth: int = 1,
    reaction_stack: list[dict[str, Any]] | None = None,
) -> ExecutionSuspended:
    decision, chosen = recommendation(opportunity)
    pending: PendingReaction = {
        "checkpoint_id": str(uuid.uuid4()),
        "trigger": trigger,
        "description": description,
        "options": [{"name": name, "label": name.replace("_", " ").title()}],
        "recommendation": {"decision": decision, "chosen_reaction": chosen},
        "plan_queue": [operation.model_dump(mode="json") for operation in plan.operations],
        "execution_cursor": cursor,
        "reaction_stack": list(reaction_stack or []),
        "depth": depth,
        "facts": facts,
        "frame": frame,
    }
    state["pending_reaction"] = pending
    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=True)
    await db.commit()
    return ExecutionSuspended(prompt=pending)


async def _apply_attack(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    state: CombatState,
    operation: AttackOperation,
    facts: list[str],
    plan: CombatPlan,
    cursor: int,
    reaction_control: ReactionControl,
    spend_action: bool = True,
) -> ExecutionOutcome | None:
    actor = find_combatant(state, operation.actor_id)
    target = find_combatant(state, operation.target_id)
    if actor is None or target is None:
        raise ValidationError("attack actor or target is not in combat", code="illegal_combat_operation")
    economy = _economy(state, actor["id"], actor["speed"])
    if spend_action and economy["action_used"]:
        raise ValidationError(f"{actor['name']} has already used their action", code="illegal_combat_operation")
    attack = await zones.attack_profile(db, actor, operation.attack_name)
    if attack is None:
        raise ValidationError(f"{actor['name']} has no legal weapon attack", code="illegal_combat_operation")
    if not target_in_range(
        state,
        source_id=actor["id"],
        target_id=target["id"],
        range_category=range_feet_to_category(int(attack["range_ft"])),
    ):
        raise ValidationError("target is outside the attack's authoritative range", code="illegal_combat_operation")

    session = await session_queries.get_session(db, session_id)
    rng = session_rng(session)
    attack_roll = roll_attack(
        to_hit_bonus=int(attack["attack_bonus"]),
        target_ac=await zones.armor_class(db, target),
        cover_ac_bonus=_cover_bonus(state, target),
        rng=rng,
    )
    damage = parse_and_roll(attack["damage_dice"], rng) if attack_roll.hit else 0
    if attack_roll.critical:
        damage += parse_and_roll(attack["damage_dice"], rng)

    target_economy = _economy(state, target["id"], target["speed"])
    shield_eligible = (
        attack_roll.hit
        and not target_economy["reaction_used"]
        and await _has_reaction_spell(db, cast(dict[str, Any], target), "shield", 1)
        and attack_roll.total < attack_roll.target_ac + 5
    )
    if shield_eligible:
        hp = await _hp(db, cast(dict[str, Any], target))
        opportunity = ReactionOpportunity(
            name="shield",
            reactor_id=target["id"],
            trigger="attack",
            changes_outcome=True,
            prevented_damage=damage,
            current_hp=hp,
            prevents_incapacitation=damage >= hp,
        )
        is_player = target["type"] == "character" and not target.get("ai_controlled", False)
        prompts_player = reaction_control == "player" or (reaction_control == "suggest" and should_react(opportunity))
        if is_player and prompts_player:
            return await _make_checkpoint(
                db,
                session_id=session_id,
                state=state,
                plan=plan,
                cursor=cursor,
                facts=facts,
                name="shield",
                trigger="attack",
                description=(
                    f"{actor['name']} attacks {target['name']}: to-hit {attack_roll.total} "
                    f"vs AC {attack_roll.target_ac} — would hit. Cast Shield?"
                ),
                opportunity=opportunity,
                frame={
                    "kind": "attack",
                    "actor_id": actor["id"],
                    "target_id": target["id"],
                    "attack": attack,
                    "roll": attack_roll.__dict__,
                    "damage": damage,
                },
            )
        if (not is_player or reaction_control == "ai") and should_react(opportunity):
            await _spend_spell_slot(db, cast(dict[str, Any], target), 1)
            target_economy["reaction_used"] = True
            damage = 0
            facts.append(f"{target['name']} cast Shield; {attack_roll.total} missed AC {attack_roll.target_ac + 5}.")

    if spend_action:
        economy["action_used"] = True
    if damage:
        result = await mutations.apply_damage(
            db,
            session_id=session_id,
            combatant_id=target["id"],
            combatant_type=target["type"],
            amount=damage,
            damage_type=str(attack["damage_type"]),
            attacker_id=actor["id"],
        )
        facts.append(
            f"{actor['name']} hit {target['name']} with {attack['name']} "
            f"({attack_roll.total} vs AC {attack_roll.target_ac}) for {damage} {attack['damage_type']} damage; "
            f"HP {result.get('hp', 'unknown')}."
        )
    elif not facts or "Shield" not in facts[-1]:
        facts.append(f"{actor['name']} missed {target['name']} ({attack_roll.total} vs AC {attack_roll.target_ac}).")
    return None


async def _fire_readied_for_event(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    state: CombatState,
    event: dict[str, object],
    facts: list[str],
) -> None:
    registry = state.setdefault("readied_actions", [])
    armed = list(registry)
    for ready in armed:
        if not matches_readied(ready["trigger"], event):
            continue
        reactor = find_combatant(state, ready["reactor_id"])
        if reactor is None:
            registry.remove(ready)
            continue
        economy = _economy(state, reactor["id"], reactor["speed"])
        if economy["reaction_used"]:
            continue
        operation_data = ready["operation"]
        operation = CombatPlan.model_validate({"operations": [operation_data]}).operations[0]
        economy["reaction_used"] = True
        registry.remove(ready)
        if isinstance(operation, AttackOperation):
            await _apply_attack(
                db,
                session_id=session_id,
                state=state,
                operation=operation,
                facts=facts,
                plan=CombatPlan(operations=(operation,)),
                cursor=0,
                reaction_control="ai",
                spend_action=False,
            )
        elif isinstance(operation, CastOperation):
            await _resolve_spell(
                db,
                session_id=session_id,
                state=state,
                operation=operation,
                facts=facts,
                plan=CombatPlan(operations=(operation,)),
                cursor=0,
                reaction_control="ai",
            )
        facts.append(f"{reactor['name']}'s readied action triggered.")


async def execute_move(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    combatant_id: str,
    target_zone_id: str,
    disengage: bool = False,
    excluded_reactors: set[str] | None = None,
) -> dict[str, Any]:
    """Execute movement and registry-owned opportunity attacks for tool and plan callers."""
    session = await session_queries.get_session(db, session_id)
    if not session.combat_active or session.combat_state is None:
        return {"error": "No active combat."}
    state = session.combat_state
    mover = find_combatant(state, combatant_id)
    if mover is None:
        return {"error": f"Combatant '{combatant_id}' not found."}
    rng = session_rng(session)
    opportunities: list[dict[str, Any]] = []
    reactors = sorted(state["combatants"], key=lambda item: item["initiative_roll"], reverse=True)
    for reactor in reactors:
        if (
            reactor["id"] == mover["id"]
            or reactor["id"] in (excluded_reactors or set())
            or reactor["team"] == mover["team"]
            or reactor["zone"] != mover["zone"]
            or not reactor["is_alive"]
            or not reactor["is_conscious"]
        ):
            continue
        economy = _economy(state, reactor["id"], reactor["speed"])
        if economy["reaction_used"]:
            continue
        sentinel = False
        if reactor["type"] != "monster":
            entity = (
                await character_queries.get_character(db, uuid.UUID(reactor["id"]))
                if reactor["type"] == "character"
                else await npc_queries.get_npc(db, uuid.UUID(reactor["id"]))
            )
            sentinel = any(feat.get("index") == "sentinel" for feat in entity.feats or [])
        if disengage and not sentinel:
            continue
        attack = await zones.melee_attack(db, reactor)
        if attack is None:
            continue
        rolled = roll_attack(
            to_hit_bonus=int(attack["attack_bonus"]),
            target_ac=await zones.armor_class(db, mover),
            cover_ac_bonus=_cover_bonus(state, mover),
            rng=rng,
        )
        damage = parse_and_roll(attack["damage_dice"], rng) if rolled.hit else 0
        if rolled.critical:
            damage += parse_and_roll(attack["damage_dice"], rng)
        economy["reaction_used"] = True
        if damage:
            await mutations.apply_damage(
                db,
                session_id=session_id,
                combatant_id=mover["id"],
                combatant_type=mover["type"],
                amount=damage,
                damage_type=str(attack["damage_type"]),
                attacker_id=reactor["id"],
            )
            if sentinel:
                _economy(state, mover["id"], mover["speed"])["movement_remaining"] = 0
        opportunities.append(
            {
                "attacker_id": reactor["id"],
                "attacker": reactor["name"],
                "attack": attack["name"],
                "attack_roll": rolled.natural,
                "attack_total": rolled.total,
                "hit": rolled.hit,
                "damage": damage,
            }
        )
        if sentinel and rolled.hit:
            break

    result = await zones.move_combatant(
        db,
        session_id=session_id,
        combatant_id=combatant_id,
        target_zone_id=target_zone_id,
    )
    if "error" not in result:
        result["opportunity_attacks"] = opportunities
    return result


async def _movement_reaction_prompt(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    state: CombatState,
    operation: MoveOperation,
    plan: CombatPlan,
    cursor: int,
    facts: list[str],
    reaction_control: ReactionControl,
) -> ExecutionSuspended | None:
    if reaction_control == "ai":
        return None
    mover = find_combatant(state, operation.actor_id)
    if mover is None:
        return None
    reactors = sorted(state["combatants"], key=lambda item: item["initiative_roll"], reverse=True)
    for reactor in reactors:
        if (
            reactor["type"] != "character"
            or reactor.get("ai_controlled", False)
            or reactor["team"] == mover["team"]
            or reactor["zone"] != mover["zone"]
            or _economy(state, reactor["id"], reactor["speed"])["reaction_used"]
        ):
            continue
        attack = await zones.melee_attack(db, reactor)
        if attack is None:
            continue
        opportunity = ReactionOpportunity(
            name="opportunity_attack",
            reactor_id=reactor["id"],
            trigger="movement",
        )
        return await _make_checkpoint(
            db,
            session_id=session_id,
            state=state,
            plan=plan,
            cursor=cursor,
            facts=facts,
            name="opportunity_attack",
            trigger="movement",
            description=f"{mover['name']} leaves {reactor['name']}'s reach. Make an opportunity attack?",
            opportunity=opportunity,
            frame={
                "kind": "movement",
                "operation": operation.model_dump(mode="json"),
                "reactor_id": reactor["id"],
                "mover_id": mover["id"],
                "attack_name": attack["name"],
            },
        )
    return None


async def _resolve_spell(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    state: CombatState,
    operation: CastOperation,
    facts: list[str],
    plan: CombatPlan,
    cursor: int,
    reaction_control: ReactionControl,
    start_index: int = 0,
    rolled_damage: int | None = None,
) -> ExecutionOutcome | None:
    caster = find_combatant(state, operation.actor_id)
    spell_record = catalog.spell(operation.spell_name)
    if caster is None or spell_record is None:
        raise ValidationError("caster or authoritative spell is unavailable", code="unsupported_spell")
    spell = spell_record.as_json()
    damage_spec = cast(dict[str, Any] | None, spell.get("damage"))
    if damage_spec is None:
        facts.append(f"{caster['name']} cast {spell_record.name}; its non-damage effect was recorded.")
        return None
    by_slot = cast(dict[str, str], damage_spec.get("damage_at_slot_level", {}))
    by_level = cast(dict[str, str], damage_spec.get("damage_at_character_level", {}))
    expression = by_slot.get(str(operation.slot_level)) or next(iter(by_level.values()), None)
    if expression is None:
        raise ValidationError("spell damage has no authoritative expression", code="unsupported_spell")
    session = await session_queries.get_session(db, session_id)
    damage_roll = rolled_damage if rolled_damage is not None else parse_and_roll(expression, session_rng(session))
    damage_type = str(cast(dict[str, Any], damage_spec["damage_type"])["index"])
    dc_spec = cast(dict[str, Any] | None, spell.get("dc"))
    save_dc = await _spell_save_dc(db, caster) if dc_spec else 0
    save_ability = str(cast(dict[str, Any], dc_spec["dc_type"])["index"]) if dc_spec else ""
    half_on_save = bool(dc_spec and dc_spec.get("dc_success") == "half")

    for target_index in range(start_index, len(operation.target_ids)):
        target_id = operation.target_ids[target_index]
        target = find_combatant(state, target_id)
        if target is None:
            facts.append(f"Spell target {target_id} was unavailable.")
            continue
        amount = damage_roll
        if dc_spec:
            save = await roll_saving_throw(
                db,
                session_id=session_id,
                combatant_id=target["id"],
                combatant_type=target["type"],
                ability=save_ability,
                dc=save_dc,
            )
            if save.get("success"):
                amount = damage_roll // 2 if half_on_save else 0
        elemental = damage_type in {"acid", "cold", "fire", "lightning", "thunder"}
        target_economy = _economy(state, target["id"], target["speed"])
        if (
            amount > 0
            and elemental
            and not target_economy["reaction_used"]
            and await _has_reaction_spell(db, cast(dict[str, Any], target), "absorb elements", 1)
        ):
            hp = await _hp(db, cast(dict[str, Any], target))
            prevented = amount - amount // 2
            opportunity = ReactionOpportunity(
                name="absorb_elements",
                reactor_id=target["id"],
                trigger="typed_damage",
                prevented_damage=prevented,
                current_hp=hp,
                prevents_incapacitation=amount >= hp and amount // 2 < hp,
            )
            is_player = target["type"] == "character" and not target.get("ai_controlled", False)
            prompts_player = is_player and (
                reaction_control == "player" or (reaction_control == "suggest" and should_react(opportunity))
            )
            if prompts_player:
                return await _make_checkpoint(
                    db,
                    session_id=session_id,
                    state=state,
                    plan=plan,
                    cursor=cursor,
                    facts=facts,
                    name="absorb_elements",
                    trigger="typed_damage",
                    description=(
                        f"{target['name']} would take {amount} {damage_type} damage from {spell_record.name}. "
                        "Cast Absorb Elements?"
                    ),
                    opportunity=opportunity,
                    frame={
                        "kind": "typed_damage",
                        "operation": operation.model_dump(mode="json"),
                        "target_index": target_index,
                        "amount": amount,
                        "damage_roll": damage_roll,
                        "damage_type": damage_type,
                    },
                )
            if (not is_player or reaction_control == "ai") and should_react(opportunity):
                await _spend_spell_slot(db, cast(dict[str, Any], target), 1)
                target_economy["reaction_used"] = True
                amount //= 2
                facts.append(f"{target['name']} used Absorb Elements against {damage_type} damage.")
        if amount:
            result = await mutations.apply_damage(
                db,
                session_id=session_id,
                combatant_id=target["id"],
                combatant_type=target["type"],
                amount=amount,
                damage_type=damage_type,
                attacker_id=caster["id"],
            )
            facts.append(
                f"{spell_record.name} dealt {amount} {damage_type} damage to {target['name']}; "
                f"HP {result.get('hp', 'unknown')}."
            )
    return None


async def _apply_cast(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    state: CombatState,
    operation: CastOperation,
    facts: list[str],
    plan: CombatPlan,
    cursor: int,
    reaction_control: ReactionControl,
) -> ExecutionOutcome | None:
    caster = find_combatant(state, operation.actor_id)
    spell = catalog.spell(operation.spell_name)
    if caster is None or spell is None or not await _can_cast(db, caster, operation.spell_name):
        raise ValidationError("caster cannot cast that authoritative spell", code="unsupported_spell")
    if operation.slot_level < spell.level:
        raise ValidationError("slot level is below the spell level", code="illegal_combat_operation")
    economy = _economy(state, caster["id"], caster["speed"])
    if economy["action_used"]:
        raise ValidationError(f"{caster['name']} has already used their action", code="illegal_combat_operation")
    await _spend_exact_slot(db, caster, operation.slot_level)
    economy["action_used"] = True

    is_area_or_control = bool(spell.as_json().get("area_of_effect") or spell.as_json().get("dc"))
    reactors = sorted(state["combatants"], key=lambda item: item["initiative_roll"], reverse=True)
    for reactor in reactors:
        reactor_economy = _economy(state, reactor["id"], reactor["speed"])
        if reactor["team"] == caster["team"] or reactor_economy["reaction_used"]:
            continue
        if not await _has_reaction_spell(db, cast(dict[str, Any], reactor), "counterspell", 3):
            continue
        opportunity = ReactionOpportunity(
            name="counterspell",
            reactor_id=reactor["id"],
            trigger="spell_cast",
            spell_level=operation.slot_level,
            is_area_or_control=is_area_or_control,
        )
        is_player = reactor["type"] == "character" and not reactor.get("ai_controlled", False)
        prompts_player = is_player and (
            reaction_control == "player" or (reaction_control == "suggest" and should_react(opportunity))
        )
        if prompts_player:
            return await _make_checkpoint(
                db,
                session_id=session_id,
                state=state,
                plan=plan,
                cursor=cursor,
                facts=facts,
                name="counterspell",
                trigger="spell_cast",
                description=f"{caster['name']} casts {spell.name} at level {operation.slot_level}. Counterspell?",
                opportunity=opportunity,
                frame={
                    "kind": "counterspell",
                    "operation": operation.model_dump(mode="json"),
                    "reactor_id": reactor["id"],
                },
            )
        if (not is_player or reaction_control == "ai") and should_react(opportunity):
            counter_level = await _spend_spell_slot(db, cast(dict[str, Any], reactor), 3)
            reactor_economy["reaction_used"] = True
            nested = next(
                (
                    candidate
                    for candidate in reactors
                    if candidate["team"] == caster["team"]
                    and not _economy(state, candidate["id"], candidate["speed"])["reaction_used"]
                    and candidate["id"] != reactor["id"]
                ),
                None,
            )
            if nested is not None and await _has_reaction_spell(db, cast(dict[str, Any], nested), "counterspell", 3):
                nested_opportunity = ReactionOpportunity(
                    name="counterspell",
                    reactor_id=nested["id"],
                    trigger="spell_cast",
                    spell_level=3,
                    is_area_or_control=True,
                )
                nested_player = nested["type"] == "character" and not nested.get("ai_controlled", False)
                if nested_player and (
                    reaction_control == "player" or (reaction_control == "suggest" and should_react(nested_opportunity))
                ):
                    return await _make_checkpoint(
                        db,
                        session_id=session_id,
                        state=state,
                        plan=plan,
                        cursor=cursor,
                        facts=facts,
                        name="counterspell",
                        trigger="spell_cast",
                        description=f"{reactor['name']} Counterspells {spell.name}. Counter their Counterspell?",
                        opportunity=nested_opportunity,
                        frame={
                            "kind": "nested_counterspell",
                            "operation": operation.model_dump(mode="json"),
                            "counterer_id": reactor["id"],
                            "reactor_id": nested["id"],
                        },
                        depth=2,
                        reaction_stack=[
                            {"reaction": "counterspell", "reactor_id": reactor["id"]},
                            {"reaction": "counterspell", "reactor_id": nested["id"]},
                        ],
                    )
            succeeds = counter_level >= operation.slot_level
            if not succeeds:
                entity = await _spell_entity(db, reactor)
                ability = entity.spellcasting_ability or "int"
                check = session_rng(await session_queries.get_session(db, session_id)).randint(1, 20)
                check += mod(get_ability_score(entity.ability_scores, ability))
                succeeds = check >= 10 + operation.slot_level
            if succeeds:
                facts.append(f"{reactor['name']} Counterspelled {caster['name']}'s {spell.name}.")
                return None
        break
    return await _resolve_spell(
        db,
        session_id=session_id,
        state=state,
        operation=operation,
        facts=facts,
        plan=plan,
        cursor=cursor,
        reaction_control=reaction_control,
    )


async def execute_plan(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    plan: CombatPlan,
    cursor: int = 0,
    facts: list[str] | None = None,
) -> ExecutionOutcome:
    session = await session_queries.get_session(db, session_id)
    if not session.combat_active or session.combat_state is None:
        raise ConflictError("session has no active combat", code="combat_inactive")
    campaign = await campaign_queries.get_campaign(db, session.campaign_id)
    reaction_control = resolve_settings(campaign.settings).reaction_control
    state = session.combat_state
    accumulated = list(facts or [])

    for index in range(cursor, len(plan.operations)):
        operation: CombatOperation = plan.operations[index]
        try:
            outcome: ExecutionOutcome | None = None
            if isinstance(operation, AttackOperation):
                outcome = await _apply_attack(
                    db,
                    session_id=session_id,
                    state=state,
                    operation=operation,
                    facts=accumulated,
                    plan=plan,
                    cursor=index,
                    reaction_control=reaction_control,
                )
            elif isinstance(operation, MoveOperation):
                movement_prompt = await _movement_reaction_prompt(
                    db,
                    session_id=session_id,
                    state=state,
                    operation=operation,
                    plan=plan,
                    cursor=index,
                    facts=accumulated,
                    reaction_control=reaction_control,
                )
                if movement_prompt is not None:
                    return movement_prompt
                result = await execute_move(
                    db,
                    session_id=session_id,
                    combatant_id=operation.actor_id,
                    target_zone_id=operation.target_zone_id,
                    disengage=operation.disengage,
                )
                if "error" in result:
                    raise ValidationError(str(result["error"]), code="illegal_combat_operation")
                accumulated.append(f"{result['combatant']} moved from {result['from_zone']} to {result['to_zone']}.")
                mover = find_combatant(state, operation.actor_id)
                if mover is not None:
                    await _fire_readied_for_event(
                        db,
                        session_id=session_id,
                        state=state,
                        event={
                            "event": "enters-zone",
                            "creature_id": mover["id"],
                            "creature_name": mover["name"],
                            "zone": result["to_zone"],
                        },
                        facts=accumulated,
                    )
            elif isinstance(operation, AdvanceTurnOperation):
                result = await state_service.advance_turn(db, session_id=session_id)
                if "error" in result:
                    raise ValidationError(str(result["error"]), code="illegal_combat_operation")
                accumulated.append(f"Turn advanced to {result['current_combatant']}.")
            elif isinstance(operation, ReadyOperation):
                if operation.parsed_trigger is None:
                    raise ValidationError(
                        "readied action must be parsed before execution",
                        code="unparsed_readied_action",
                    )
                actor = find_combatant(state, operation.actor_id)
                if actor is None:
                    raise ValidationError("readied actor is not in combat", code="illegal_combat_operation")
                economy = _economy(state, actor["id"], actor["speed"])
                if economy["action_used"]:
                    raise ValidationError(f"{actor['name']} has already used their action")
                economy["action_used"] = True
                state.setdefault("readied_actions", []).append(
                    {
                        "reactor_id": actor["id"],
                        "trigger": operation.parsed_trigger.model_dump(mode="json"),
                        "operation": operation.action.model_dump(mode="json"),
                        "expires_round": state["round"] + 1,
                    }
                )
                accumulated.append(f"{actor['name']} readied {operation.action.kind}: {operation.trigger}.")
            elif isinstance(operation, ApplyConditionOperation):
                actor = find_combatant(state, operation.actor_id)
                target = find_combatant(state, operation.target_id)
                if actor is None or target is None or rules.get_condition(operation.condition) is None:
                    raise ValidationError("condition actor, target, or SRD condition is unavailable")
                result = await mutations.apply_condition(
                    db,
                    session_id=session_id,
                    combatant_id=target["id"],
                    condition=operation.condition,
                )
                if "error" in result:
                    raise ValidationError(str(result["error"]), code="illegal_combat_operation")
                accumulated.append(f"{actor['name']} applied {operation.condition} to {target['name']}.")
            elif isinstance(operation, EndCombatOperation):
                await state_service.end_state(db, session_id=session_id)
                accumulated.append(f"Combat ended: {operation.outcome}.")
                await db.commit()
                return ExecutionComplete(facts=tuple(accumulated))
            elif isinstance(operation, CastOperation):
                outcome = await _apply_cast(
                    db,
                    session_id=session_id,
                    state=state,
                    operation=operation,
                    facts=accumulated,
                    plan=plan,
                    cursor=index,
                    reaction_control=reaction_control,
                )
            if outcome is not None:
                return outcome
        except ValidationError as exc:
            accumulated.append(f"Plan stopped: {exc.message}")
            break

    state.pop("pending_reaction", None)
    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=True)
    await db.commit()
    return ExecutionComplete(facts=tuple(accumulated))


async def resume_reaction(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
    checkpoint_id: str,
    decision: str,
    chosen_reaction: str | None,
) -> ExecutionOutcome:
    session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, session.campaign_id, owner_id)
    state = session.combat_state
    pending = state.get("pending_reaction") if state else None
    if pending is None or pending["checkpoint_id"] != checkpoint_id:
        raise ConflictError("reaction checkpoint is missing or stale", code="stale_reaction")
    assert state is not None
    if decision == "take":
        legal = {option["name"] for option in pending["options"]}
        if chosen_reaction not in legal:
            raise ValidationError("chosen_reaction is not a legal option", code="invalid_reaction")
    elif chosen_reaction is not None:
        raise ValidationError("chosen_reaction must be null when declining", code="invalid_reaction")

    frame = pending["frame"]
    facts = list(pending["facts"])
    plan = CombatPlan.model_validate({"operations": pending["plan_queue"]})
    campaign = await campaign_queries.get_campaign(db, session.campaign_id)
    reaction_control = resolve_settings(campaign.settings).reaction_control
    continuation: ExecutionOutcome | None = None
    if frame.get("kind") == "attack":
        actor = find_combatant(state, str(frame["actor_id"]))
        target = find_combatant(state, str(frame["target_id"]))
        if actor is None or target is None:
            raise ConflictError("reaction actors are no longer present", code="stale_reaction")
        attack = cast(dict[str, Any], frame["attack"])
        rolled = AttackRoll(**cast(dict[str, Any], frame["roll"]))
        damage = int(frame["damage"])
        if decision == "take" and chosen_reaction == "shield":
            await _spend_spell_slot(db, cast(dict[str, Any], target), 1)
            _economy(state, target["id"], target["speed"])["reaction_used"] = True
            damage = 0
            facts.append(f"{target['name']} cast Shield; {rolled.total} missed AC {rolled.target_ac + 5}.")
        if damage:
            result = await mutations.apply_damage(
                db,
                session_id=session_id,
                combatant_id=target["id"],
                combatant_type=target["type"],
                amount=damage,
                damage_type=str(attack["damage_type"]),
                attacker_id=actor["id"],
            )
            facts.append(f"{actor['name']} hit {target['name']} for {damage}; HP {result.get('hp', 'unknown')}.")
        elif decision == "decline":
            facts.append(f"{target['name']} declined Shield; the attack missed or dealt no damage.")
        _economy(state, actor["id"], actor["speed"])["action_used"] = True
    elif frame.get("kind") == "counterspell":
        operation = CastOperation.model_validate(frame["operation"])
        caster = find_combatant(state, operation.actor_id)
        reactor = find_combatant(state, str(frame["reactor_id"]))
        if caster is None or reactor is None:
            raise ConflictError("counterspell actors are no longer present", code="stale_reaction")
        if decision == "take" and chosen_reaction == "counterspell":
            await _spend_spell_slot(db, cast(dict[str, Any], reactor), 3)
            _economy(state, reactor["id"], reactor["speed"])["reaction_used"] = True
            facts.append(f"{reactor['name']} Counterspelled {caster['name']}'s {operation.spell_name}.")
        else:
            facts.append(f"{reactor['name']} declined Counterspell.")
            continuation = await _resolve_spell(
                db,
                session_id=session_id,
                state=state,
                operation=operation,
                facts=facts,
                plan=plan,
                cursor=pending["execution_cursor"],
                reaction_control=reaction_control,
            )
    elif frame.get("kind") == "typed_damage":
        operation = CastOperation.model_validate(frame["operation"])
        target_index = int(frame["target_index"])
        target = find_combatant(state, operation.target_ids[target_index])
        caster = find_combatant(state, operation.actor_id)
        if target is None or caster is None:
            raise ConflictError("damage reaction actors are no longer present", code="stale_reaction")
        amount = int(frame["amount"])
        if decision == "take" and chosen_reaction == "absorb_elements":
            await _spend_spell_slot(db, cast(dict[str, Any], target), 1)
            _economy(state, target["id"], target["speed"])["reaction_used"] = True
            amount //= 2
            facts.append(f"{target['name']} used Absorb Elements.")
        if amount:
            result = await mutations.apply_damage(
                db,
                session_id=session_id,
                combatant_id=target["id"],
                combatant_type=target["type"],
                amount=amount,
                damage_type=str(frame["damage_type"]),
                attacker_id=caster["id"],
            )
            facts.append(f"{operation.spell_name} dealt {amount} damage; HP {result.get('hp', 'unknown')}.")
        continuation = await _resolve_spell(
            db,
            session_id=session_id,
            state=state,
            operation=operation,
            facts=facts,
            plan=plan,
            cursor=pending["execution_cursor"],
            reaction_control=reaction_control,
            start_index=target_index + 1,
            rolled_damage=int(frame["damage_roll"]),
        )
    elif frame.get("kind") == "movement":
        move_operation = MoveOperation.model_validate(frame["operation"])
        reactor = find_combatant(state, str(frame["reactor_id"]))
        mover = find_combatant(state, str(frame["mover_id"]))
        if reactor is None or mover is None:
            raise ConflictError("movement reaction actors are no longer present", code="stale_reaction")
        if decision == "take" and chosen_reaction == "opportunity_attack":
            _economy(state, reactor["id"], reactor["speed"])["reaction_used"] = True
            attack_operation = AttackOperation(
                kind="attack",
                actor_id=reactor["id"],
                target_id=mover["id"],
                attack_name=str(frame["attack_name"]),
            )
            await _apply_attack(
                db,
                session_id=session_id,
                state=state,
                operation=attack_operation,
                facts=facts,
                plan=CombatPlan(operations=(attack_operation,)),
                cursor=0,
                reaction_control="ai",
                spend_action=False,
            )
        result = await execute_move(
            db,
            session_id=session_id,
            combatant_id=move_operation.actor_id,
            target_zone_id=move_operation.target_zone_id,
            disengage=move_operation.disengage,
            excluded_reactors={reactor["id"]},
        )
        if "error" in result:
            facts.append(f"Movement stopped: {result['error']}")
        else:
            facts.append(f"{result['combatant']} moved to {result['to_zone']}.")
    elif frame.get("kind") == "nested_counterspell":
        operation = CastOperation.model_validate(frame["operation"])
        reactor = find_combatant(state, str(frame["reactor_id"]))
        counterer = find_combatant(state, str(frame["counterer_id"]))
        if reactor is None or counterer is None:
            raise ConflictError("nested reaction actors are no longer present", code="stale_reaction")
        if decision == "take" and chosen_reaction == "counterspell":
            await _spend_spell_slot(db, cast(dict[str, Any], reactor), 3)
            _economy(state, reactor["id"], reactor["speed"])["reaction_used"] = True
            facts.append(f"{reactor['name']} Counterspelled {counterer['name']}'s Counterspell.")
            continuation = await _resolve_spell(
                db,
                session_id=session_id,
                state=state,
                operation=operation,
                facts=facts,
                plan=plan,
                cursor=pending["execution_cursor"],
                reaction_control=reaction_control,
            )
        else:
            facts.append(f"{reactor['name']} declined; {counterer['name']}'s Counterspell succeeded.")

    state.pop("pending_reaction", None)
    await session_queries.update_combat_state(db, session_id, combat_state=state, combat_active=True)
    await db.commit()
    if continuation is not None:
        return continuation
    return await execute_plan(
        db,
        session_id=session_id,
        plan=plan,
        cursor=pending["execution_cursor"] + 1,
        facts=facts,
    )
