from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph

from cairn.agents import intent_router
from cairn.application.turns import resolvers as turn_resolvers
from cairn.application.turns import transitions as turn_transitions
from cairn.application.turns.types import CheckData
from cairn.domain.scenes import ScenePreOutput
from cairn.domain.services.settings import ResolvedCampaignSettings
from cairn.pipelines.checkpointer import get_checkpointer

log = structlog.get_logger()


class TurnState(TypedDict):
    session_id: str
    campaign_id: str
    player_input: str
    intent: str | None
    npc_name: str | None
    check: CheckData | None  # set by resolve_skill_check; consumed by route layer
    npc_context: str | None  # set by resolve_dialogue; consumed by route layer
    rest_context: str | None  # set by resolve_rest; consumed by route layer
    scene_pre_output: ScenePreOutput | None  # set by scene_director_pre; None when combat already active
    is_scene_entry: bool  # set by scene_create; consumed by route layer for narration
    combat_just_started: bool  # set by combat_entry when init_state ran
    settings: ResolvedCampaignSettings  # resolved once by turns.prepare; shared snapshot for the whole turn


async def _route_intent(state: TurnState) -> dict[str, Any]:
    intent, npc_name = await intent_router.run(state["player_input"])
    log.info("intent_classified", intent=intent, npc_name=npc_name)
    return {"intent": intent, "npc_name": npc_name}


async def _resolve_skill_check(state: TurnState) -> dict[str, Any]:
    return await turn_resolvers.resolve_skill_check(state)


async def _resolve_rest(state: TurnState) -> dict[str, Any]:
    return await turn_resolvers.resolve_rest(state)


async def _resolve_dialogue(state: TurnState) -> dict[str, Any]:
    return await turn_resolvers.resolve_dialogue(state)


async def _resolve_recruitment(state: TurnState) -> dict[str, Any]:
    return await turn_resolvers.resolve_recruitment(state)


async def _resolve_dismissal(state: TurnState) -> dict[str, Any]:
    return await turn_resolvers.resolve_dismissal(state)


async def _scene_director_pre(state: TurnState) -> dict[str, Any]:
    return await turn_transitions.scene_director_pre(state)


def _after_pre(state: TurnState) -> str:
    pre = state["scene_pre_output"]
    if pre is None:
        return "combat_terminus"  # combat already active — straight to resolution
    trigger = pre["combat_trigger"]
    if trigger and trigger["hostile_npc_ids"]:
        return "combat_entry"
    if pre["scene_transition_pull"] is not None:
        return "scene_create"
    return "route_intent"


async def _combat_entry(state: TurnState) -> dict[str, Any]:
    return await turn_transitions.combat_entry(state)


def _after_combat_entry(state: TurnState) -> str:
    return "combat_terminus" if state["combat_just_started"] else "route_intent"


async def _combat_terminus(state: TurnState) -> dict[str, Any]:
    """Terminal for combat turns — the route layer streams combat_resolver on this intent."""
    return {"intent": "combat_action"}


async def _scene_create(state: TurnState) -> dict[str, Any]:
    return await turn_transitions.scene_create(state)


def _pick_node(state: TurnState) -> str:
    intent = state["intent"]
    if intent == "skill_check":
        return "resolve_skill_check"
    if intent == "npc_dialogue":
        return "resolve_dialogue"
    if intent == "rest_action":
        return "resolve_rest"
    if intent == "recruit_attempt":
        return "resolve_recruitment"
    if intent == "dismiss_companion":
        return "resolve_dismissal"
    return END


@lru_cache(maxsize=1)
def _get_graph() -> Any:
    builder: StateGraph = StateGraph(TurnState)
    builder.add_node("scene_director_pre", _scene_director_pre)
    builder.add_node("combat_entry", _combat_entry)
    builder.add_node("combat_terminus", _combat_terminus)
    builder.add_node("scene_create", _scene_create)
    builder.add_node("route_intent", _route_intent)
    builder.add_node("resolve_skill_check", _resolve_skill_check)
    builder.add_node("resolve_dialogue", _resolve_dialogue)
    builder.add_node("resolve_rest", _resolve_rest)
    builder.add_node("resolve_recruitment", _resolve_recruitment)
    builder.add_node("resolve_dismissal", _resolve_dismissal)

    builder.add_edge(START, "scene_director_pre")
    builder.add_conditional_edges(
        "scene_director_pre",
        _after_pre,
        ["combat_terminus", "combat_entry", "scene_create", "route_intent"],
    )
    builder.add_conditional_edges("combat_entry", _after_combat_entry, ["combat_terminus", "route_intent"])
    builder.add_edge("combat_terminus", END)
    builder.add_edge("scene_create", "route_intent")
    builder.add_conditional_edges("route_intent", _pick_node)
    builder.add_edge("resolve_skill_check", END)
    builder.add_edge("resolve_dialogue", END)
    builder.add_edge("resolve_rest", END)
    builder.add_edge("resolve_recruitment", END)
    builder.add_edge("resolve_dismissal", END)

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
            scene_pre_output=None,
            is_scene_entry=False,
            combat_just_started=False,
            settings=ResolvedCampaignSettings(),
        ),
        config=config,
    )
    return result
