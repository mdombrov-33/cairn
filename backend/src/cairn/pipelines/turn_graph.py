from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph

from cairn.agents import (
    intent_router,
    rules_lawyer,
)
from cairn.agents import npc_dialogue as npc_dialogue_agent
from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.pipelines.checkpointer import get_checkpointer
from cairn.types import CheckData, HelperRef

log = structlog.get_logger()


class TurnState(TypedDict):
    session_id: str
    campaign_id: str
    player_input: str
    intent: str | None
    npc_name: str | None
    check: CheckData | None  # set by resolve_skill_check; consumed by route layer
    npc_context: str | None  # set by resolve_npc_dialogue; consumed by route layer
    rest_context: str | None  # set by resolve_rest; consumed by route layer


async def _route_intent(state: TurnState) -> dict[str, Any]:
    intent, npc_name = await intent_router.run(state["player_input"])
    log.info("intent_classified", intent=intent, npc_name=npc_name)
    return {"intent": intent, "npc_name": npc_name}


async def _resolve_skill_check(state: TurnState) -> dict[str, Any]:
    session_id = uuid.UUID(state["session_id"])

    async with db_client.get_session() as db:
        party = await character_queries.get_party_for_session(db, session_id)

    # Active character: prefer the PC (non-companion); fall back to first available.
    active = next((c for c in party if not c.is_companion), party[0] if party else None)

    party_views = [rules_lawyer.CharacterView.from_character(c) for c in party]
    active_view = rules_lawyer.CharacterView.from_character(active) if active else None

    character_context = rules_lawyer.build_character_context(active_view) if active_view else ""
    party_manifest = rules_lawyer.build_party_manifest(party_views, active.id) if active else ""

    check = await rules_lawyer.run(
        state["player_input"],
        character_context=character_context,
        party_manifest=party_manifest,
    )

    check_dict: CheckData = {
        "skill": check.skill,
        "dc": check.dc,
        "modifier": check.modifier,
        "roll_type": check.roll_type,
        "status": "pending",
    }
    if check.helper:
        party_ids = {str(c.id) for c in party}
        if check.helper.character_id in party_ids:
            helper: HelperRef = {
                "character_id": check.helper.character_id,
                "name": check.helper.name,
            }
            check_dict["helper"] = helper
        else:
            log.warning(
                "rules_lawyer_invalid_helper",
                helper_id=check.helper.character_id,
                party_ids=list(party_ids),
            )

    return {"check": check_dict}


def _infer_rest_type(text: str) -> str:
    lowered = text.lower()
    long_words = ("long rest", "camp", "sleep", "night", "8 hour", "full rest", "dawn", "morning")
    return "long" if any(w in lowered for w in long_words) else "short"


async def _resolve_rest(state: TurnState) -> dict[str, Any]:
    from cairn.domain.exceptions import ConflictError
    from cairn.domain.services import rests as rest_service

    session_id = uuid.UUID(state["session_id"])
    rest_type = _infer_rest_type(state["player_input"])

    async with db_client.get_session() as db:
        try:
            if rest_type == "long":
                result = await rest_service.apply_long_rest(db, session_id=session_id)
            else:
                result = await rest_service.apply_short_rest(db, session_id=session_id)
            context = rest_service.build_rest_context(rest_type, result)
        except ConflictError as e:
            context = rest_service.build_blocked_context(e.code)

    log.info("rest_resolved", session_id=state["session_id"], rest_type=rest_type)
    return {"rest_context": context}


async def _resolve_npc_dialogue(state: TurnState) -> dict[str, Any]:

    campaign_id = uuid.UUID(state["campaign_id"])
    npc_name = state["npc_name"] or ""

    async with db_client.get_session() as db:
        npc = await npc_queries.find_by_name(db, campaign_id, npc_name)
        if npc is None:
            return {"npc_context": ""}

        result = await npc_dialogue_agent.run(state["player_input"], npc)
        npc_context = f'[{npc.name}]: "{result.dialogue}"'

        if result.disposition_change:
            npc.disposition = result.disposition_change
            await db.commit()

    return {"npc_context": npc_context}


def _pick_node(state: TurnState) -> str:
    intent = state["intent"]
    if intent == "skill_check":
        return "resolve_skill_check"
    if intent == "npc_dialogue":
        return "resolve_npc_dialogue"
    if intent == "rest_action":
        return "resolve_rest"
    return END


@lru_cache(maxsize=1)
def _get_graph() -> Any:
    builder: StateGraph = StateGraph(TurnState)
    builder.add_node("route_intent", _route_intent)
    builder.add_node("resolve_skill_check", _resolve_skill_check)
    builder.add_node("resolve_npc_dialogue", _resolve_npc_dialogue)
    builder.add_node("resolve_rest", _resolve_rest)

    builder.add_edge(START, "route_intent")
    builder.add_conditional_edges("route_intent", _pick_node)
    builder.add_edge("resolve_skill_check", END)
    builder.add_edge("resolve_npc_dialogue", END)
    builder.add_edge("resolve_rest", END)

    return builder.compile(checkpointer=get_checkpointer())


async def run(
    player_input: str,
    session_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> TurnState:
    graph = _get_graph()
    config = {"configurable": {"thread_id": str(session_id)}}
    result = await graph.ainvoke(
        TurnState(
            session_id=str(session_id),
            campaign_id=str(campaign_id),
            player_input=player_input,
            intent=None,
            npc_name=None,
            check=None,
            npc_context=None,
            rest_context=None,
        ),
        config=config,
    )
    return result
