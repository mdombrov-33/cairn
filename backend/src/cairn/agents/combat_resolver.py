import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, TypedDict

import structlog

from cairn.agents import combat_ai, readied_parser, scene_narrator
from cairn.application.combat import executor
from cairn.application.combat.emitter import emit
from cairn.application.combat.plan import CombatPlan
from cairn.context import current_campaign_settings
from cairn.db import client as db_client
from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete_to_model
from cairn.llm.router import agent_setup
from cairn.tools import fetch_combat_context

log = structlog.get_logger()


class PendingCompanionProposal(TypedDict):
    combatant_id: str
    combatant_name: str
    action: str
    narration: str


@dataclass(frozen=True)
class CombatResolution:
    context: str
    proposal: PendingCompanionProposal | None = None
    suspension: executor.ExecutionSuspended | None = None


async def resolve(
    player_input: str,
    session_id: str,
    context: str = "",
    *,
    prior_context: str = "",
) -> CombatResolution:
    """Resolve a combat instruction until narration is possible or a companion proposes a turn."""
    player_plan = await _plan(player_input, session_id, context)
    player_outcome = await _execute_plan(session_id, player_plan)
    if isinstance(player_outcome, executor.ExecutionSuspended):
        return CombatResolution(context=prior_context, suspension=player_outcome)
    summaries = [f"[PLAYER ACTION]\n{' '.join(player_outcome.facts)}"]

    initial_state, _ = await fetch_combat_context(session_id)
    cap = len(initial_state.get("combatants", [])) if initial_state else 0
    settings = current_campaign_settings.get()
    companion_mode = settings.companion.combat if settings is not None else "ai"

    for _ in range(cap):
        combat_state, party = await fetch_combat_context(session_id)
        if not combat_state:
            break
        combatants = combat_state.get("combatants", [])
        if not combatants:
            break
        current = combatants[combat_state.get("turn_index", 0)]
        if not current.get("is_alive", True):
            break
        companion = next(
            (member for member in party if member.get("id") == current["id"] and member.get("is_companion")), None
        )
        if companion is not None and companion_mode == "player":
            break
        if companion is not None and companion_mode == "suggest":
            proposal = await combat_ai.propose(session_id)
            combined = "\n\n".join(part for part in [prior_context, *summaries] if part)
            return CombatResolution(
                context=combined,
                proposal={
                    "combatant_id": current["id"],
                    "combatant_name": current["name"],
                    "action": proposal.action,
                    "narration": proposal.narration,
                },
            )
        if current["type"] == "character" and not current.get("ai_controlled"):
            break
        role: Literal["ally", "enemy"] = "ally" if current.get("team") == "players" else "enemy"
        try:
            plan = await combat_ai.run(session_id, role=role)
            outcome = await _execute_plan(session_id, plan)
            if isinstance(outcome, executor.ExecutionSuspended):
                combined = "\n\n".join(part for part in [prior_context, *summaries] if part)
                return CombatResolution(context=combined, suspension=outcome)
            summary = " ".join(outcome.facts)
        except Exception as exc:
            log.error("combat_step_failed", error=str(exc), session_id=session_id)
            async with db_client.get_session() as db:
                await emit(db, {"type": "combat_step_failed", "error": str(exc)})
                await db.commit()
            raise
        summaries.append(f"[{'ALLY' if role == 'ally' else 'ENEMY'} TURN]\n{summary}")

    combined = "\n\n".join(part for part in [prior_context, *summaries, context] if part)
    return CombatResolution(context=combined)


async def run(
    player_input: str,
    session_id: str,
    context: str = "",
) -> AsyncIterator[str]:
    """Resolve a combat action and stream the narrative.

    Phase 1: Resolve player action via tool loop.
    Phase 2: Loop ally/enemy turns until it's the player's character's turn again.
    Phase 3: Narrate everything together.
    """
    resolution = await resolve(player_input, session_id, context)
    if resolution.proposal is not None or resolution.suspension is not None:
        return

    async for chunk in scene_narrator.run(player_input, context=resolution.context):
        yield chunk


async def _plan(
    player_input: str,
    session_id: str,
    context: str,
) -> CombatPlan:
    prompt, model, fallbacks = agent_setup("combat_resolver")

    combat_state, party = await fetch_combat_context(session_id)

    rendered = prompt.render(
        session_id=session_id,
        player_input=player_input,
        context=context,
        combat_state=json.dumps(combat_state, indent=2) if combat_state else None,
        party=json.dumps(party, indent=2) if party else None,
    )
    messages = [{"role": "user", "content": rendered}]

    try:
        plan = await complete_to_model(
            model=model,
            messages=messages,
            model_cls=CombatPlan,
            agent="combat_resolver",
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
        operations = []
        for operation in plan.operations:
            if operation.kind == "ready" and operation.parsed_trigger is None:
                parsed = await readied_parser.run(
                    operation.trigger,
                    combat_context=json.dumps(combat_state, indent=2),
                )
                operation = operation.model_copy(update={"parsed_trigger": parsed})
            operations.append(operation)
        return plan.model_copy(update={"operations": tuple(operations)})
    except Exception as exc:
        log.error("combat_resolver_failed", error=str(exc))
        raise AgentError(f"CombatResolver failed: {exc}") from exc


async def _execute_plan(session_id: str, plan: CombatPlan) -> executor.ExecutionOutcome:
    async with db_client.get_session() as db:
        return await executor.execute_plan(db, session_id=uuid.UUID(session_id), plan=plan)
