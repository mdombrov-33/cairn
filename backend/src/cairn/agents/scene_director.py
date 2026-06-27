"""Scene Director — the DM's meta-router.

Two LLM passes per turn, both non-streaming pre/post-processing:
  - `run_pre`  (latency-critical): detects combat triggers and player-pulled scene
    transitions before the turn streams.
  - `run_post` (background): observes the streamed narration and detects scene
    pushes, time advancement, act progress, and combat end.

Both parse-fail safe: an unparseable model response degrades to "no meta event"
rather than raising, so a flaky director never blocks a turn.
"""

import structlog
from pydantic import BaseModel

from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete_to_model
from cairn.llm.router import agent_setup
from cairn.types import CombatTrigger, ScenePostOutput, ScenePreOutput, SceneTransition

log = structlog.get_logger()


class _CombatTrigger(BaseModel):
    hostile_npc_ids: list[str]


class _SceneTransition(BaseModel):
    to_location_id: str
    reason: str


class _PreDecision(BaseModel):
    combat_trigger: _CombatTrigger | None = None
    scene_transition_pull: _SceneTransition | None = None
    pacing_nudge: str | None = None


class _PostDecision(BaseModel):
    combat_ended: bool = False
    scene_transition_push: _SceneTransition | None = None
    time_advance_hours: int = 0
    act_progress: bool = False


def _empty_pre() -> ScenePreOutput:
    return {"combat_trigger": None, "scene_transition_pull": None, "pacing_nudge": None}


def _empty_post() -> ScenePostOutput:
    return {
        "combat_ended": False,
        "scene_transition_push": None,
        "time_advance_hours": 0,
        "act_progress": False,
    }


def _trigger(t: _CombatTrigger | None) -> CombatTrigger | None:
    return {"hostile_npc_ids": t.hostile_npc_ids} if t else None


def _transition(t: _SceneTransition | None) -> SceneTransition | None:
    return {"to_location_id": t.to_location_id, "reason": t.reason} if t else None


async def run_pre(context: dict) -> ScenePreOutput:
    prompt, model, fallbacks = agent_setup("scene_director_pre")
    try:
        decision = await complete_to_model(
            model=model,
            messages=[{"role": "user", "content": prompt.render(**context)}],
            model_cls=_PreDecision,
            agent="scene_director_pre",
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
    except AgentError:
        log.warning("scene_director_pre_parse_failed")
        return _empty_pre()

    return {
        "combat_trigger": _trigger(decision.combat_trigger),
        "scene_transition_pull": _transition(decision.scene_transition_pull),
        "pacing_nudge": None,  # schema slot only in this slice
    }


async def run_post(context: dict) -> ScenePostOutput:
    prompt, model, fallbacks = agent_setup("scene_director_post")
    try:
        decision = await complete_to_model(
            model=model,
            messages=[{"role": "user", "content": prompt.render(**context)}],
            model_cls=_PostDecision,
            agent="scene_director_post",
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
    except AgentError:
        log.warning("scene_director_post_parse_failed")
        return _empty_post()

    push = _transition(decision.scene_transition_push)
    # Time only advances at a scene boundary — discard a stray hours value otherwise.
    hours = decision.time_advance_hours if push and decision.time_advance_hours > 0 else 0
    return {
        "combat_ended": decision.combat_ended,
        "scene_transition_push": push,
        "time_advance_hours": hours,
        "act_progress": decision.act_progress,
    }
