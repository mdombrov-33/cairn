import json
from collections.abc import AsyncIterator
from typing import Literal, TypedDict

import structlog

from cairn.agents import combat_ai, scene_narrator
from cairn.context import current_campaign_settings
from cairn.db import client as db_client
from cairn.domain.exceptions import AgentError
from cairn.domain.services.combat.emitter import emit
from cairn.llm.client import complete_with_tools
from cairn.llm.router import agent_setup
from cairn.tools import COMBAT_TOOLS, fetch_combat_context

log = structlog.get_logger()


class PendingCompanionProposal(TypedDict):
    combatant_id: str
    combatant_name: str
    action: str
    narration: str


async def resolve(
    player_input: str,
    session_id: str,
    context: str = "",
    *,
    prior_context: str = "",
) -> tuple[str, PendingCompanionProposal | None]:
    """Resolve a combat instruction until narration is possible or a companion proposes a turn."""
    player_summary = await _resolve_mechanics(player_input, session_id, context)
    summaries = [f"[PLAYER ACTION]\n{player_summary}"]

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
            return combined, {
                "combatant_id": current["id"],
                "combatant_name": current["name"],
                "action": proposal.action,
                "narration": proposal.narration,
            }
        if current["type"] == "character" and not current.get("ai_controlled"):
            break
        role: Literal["ally", "enemy"] = "ally" if current.get("team") == "players" else "enemy"
        try:
            summary = await combat_ai.run(session_id, role=role)
        except Exception as exc:
            log.error("combat_step_failed", error=str(exc), session_id=session_id)
            async with db_client.get_session() as db:
                await emit(db, {"type": "combat_step_failed", "error": str(exc)})
                await db.commit()
            raise
        summaries.append(f"[{'ALLY' if role == 'ally' else 'ENEMY'} TURN]\n{summary}")

    combined = "\n\n".join(part for part in [prior_context, *summaries, context] if part)
    return combined, None


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
    narrative_context, proposal = await resolve(player_input, session_id, context)
    if proposal is not None:
        return

    async for chunk in scene_narrator.run(player_input, context=narrative_context):
        yield chunk


async def _resolve_mechanics(
    player_input: str,
    session_id: str,
    context: str,
) -> str:
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
        final_text, _ = await complete_with_tools(
            model=model,
            messages=messages,
            tools=COMBAT_TOOLS,
            agent="combat_resolver",
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
    except Exception as exc:
        log.error("combat_resolver_failed", error=str(exc))
        raise AgentError(f"CombatResolver failed: {exc}") from exc

    try:
        data = json.loads(final_text.strip())
        return str(data.get("summary", final_text))
    except json.JSONDecodeError:
        log.warning("combat_resolver_non_json_response", raw=final_text[:200])
        return final_text
