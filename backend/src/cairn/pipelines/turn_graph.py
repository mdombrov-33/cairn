from __future__ import annotations

import uuid
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph

from cairn.agents import intent_router
from cairn.pipelines.checkpointer import get_checkpointer

log = structlog.get_logger()


class TurnState(TypedDict):
    player_input: str
    intent: str | None


async def _route_intent(state: TurnState) -> dict[str, Any]:
    intent = await intent_router.run(state["player_input"])
    log.info("intent_classified", intent=intent)
    return {"intent": intent}


_graph: Any = None


def _get_graph() -> Any:
    global _graph
    if _graph is None:
        builder: StateGraph = StateGraph(TurnState)
        builder.add_node("route_intent", _route_intent)
        builder.add_edge(START, "route_intent")
        builder.add_edge("route_intent", END)
        _graph = builder.compile(checkpointer=get_checkpointer())
    return _graph


async def run(player_input: str, session_id: uuid.UUID) -> str | None:
    graph = _get_graph()
    config = {"configurable": {"thread_id": str(session_id)}}
    result = await graph.ainvoke(
        {"player_input": player_input, "intent": None},
        config=config,
    )
    return result.get("intent")
