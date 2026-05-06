from __future__ import annotations

import uuid
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph

from cairn.agents import (
    intent_router,
    rules_lawyer,
)
from cairn.agents import npc_dialogue as npc_dialogue_agent
from cairn.db import client as db_client
from cairn.db.queries import npcs as npc_queries
from cairn.pipelines.checkpointer import get_checkpointer

log = structlog.get_logger()


class TurnState(TypedDict):
    session_id: str
    campaign_id: str
    player_input: str
    intent: str | None
    npc_name: str | None
    check: dict | None  # set by resolve_skill_check; consumed by route layer
    npc_context: str | None  # set by resolve_npc_dialogue; consumed by route layer


async def _route_intent(state: TurnState) -> dict[str, Any]:
    intent, npc_name = await intent_router.run(state["player_input"])
    log.info("intent_classified", intent=intent, npc_name=npc_name)
    return {"intent": intent, "npc_name": npc_name}


async def _resolve_skill_check(state: TurnState) -> dict[str, Any]:

    check = await rules_lawyer.run(state["player_input"])
    return {
        "check": {
            "skill": check.skill,
            "dc": check.dc,
            "modifier": check.modifier,
            "roll_type": check.roll_type,
            "status": "pending",
        }
    }


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
    return END


_graph: Any = None


def _get_graph() -> Any:
    global _graph
    if _graph is None:
        builder: StateGraph = StateGraph(TurnState)
        builder.add_node("route_intent", _route_intent)
        builder.add_node("resolve_skill_check", _resolve_skill_check)
        builder.add_node("resolve_npc_dialogue", _resolve_npc_dialogue)

        builder.add_edge(START, "route_intent")
        builder.add_conditional_edges("route_intent", _pick_node)
        builder.add_edge("resolve_skill_check", END)
        builder.add_edge("resolve_npc_dialogue", END)

        _graph = builder.compile(checkpointer=get_checkpointer())
    return _graph


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
        ),
        config=config,
    )
    return result
