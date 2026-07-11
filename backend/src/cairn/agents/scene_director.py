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
from pydantic import BaseModel, Field

from cairn.domain.exceptions import AgentError
from cairn.domain.scenes import CombatTrigger, NpcPresence, SceneMood, ScenePostOutput, ScenePreOutput, SceneTransition
from cairn.llm.client import complete_to_model
from cairn.llm.router import agent_setup

log = structlog.get_logger()

# Pacing-nudge thresholds. The nudge is computed deterministically from scene state — it is
# never an LLM decision. Stalling is keyed on turns-since-last-revelation (not raw turn count),
# so an engaged scene that keeps surfacing things is never nudged however long it runs.
_EARLY_BEAT = 5
_STALL_SILENCE = 15
_TENSION_ESCALATION = 7

_VALID_MOODS: frozenset[str] = frozenset(("quiet", "charged", "hostile", "intimate"))


def compute_pacing_nudge(
    *, scene_mode: str, beat_count: int, tension_level: int, turns_since_revelation: int
) -> str | None:
    """Soft guidance for the narrator, derived purely from scene state. Never forces an outcome.

    Priority: a live escalation beats a stall, a stall beats early-scene descriptiveness. Returns
    None when the scene is pacing itself fine. `turns_since_revelation` is the stall signal — for a
    scene that has never revealed anything it equals the beat count, so a long silent scene stalls
    while a long scene full of discoveries does not.
    """
    if tension_level > _TENSION_ESCALATION:
        return (
            "Escalation point available — an NPC could turn, a threat could land, or a revelation "
            "could break. Offer it; do not force it."
        )
    if turns_since_revelation > _STALL_SILENCE:
        return (
            "This scene is stalling — surface a hidden detail through an environmental cue, advance "
            "an NPC's agenda, or drop a hook. Do not resolve it for the player."
        )
    if scene_mode == "exploration" and beat_count < _EARLY_BEAT:
        return "Early in the scene — stay descriptive and let the player probe. Do not rush to a revelation."
    return None


class _CombatTrigger(BaseModel):
    hostile_npc_ids: list[str]


class _SceneTransition(BaseModel):
    to_location_id: str
    reason: str


class _NpcUpdate(BaseModel):
    npc_id: str
    doing: str | None = None
    attentive_to: list[str] | None = None
    agenda: str | None = None


class _PreDecision(BaseModel):
    combat_trigger: _CombatTrigger | None = None
    scene_transition_pull: _SceneTransition | None = None


class _PostDecision(BaseModel):
    combat_ended: bool = False
    scene_transition_push: _SceneTransition | None = None
    time_advance_hours: int = 0
    act_progress: bool = False
    tension_delta: int = 0
    mood: str | None = None  # validated against _VALID_MOODS at mapping time
    discovered: list[str] = Field(default_factory=list)
    threads_added: list[str] = Field(default_factory=list)
    threads_resolved: list[str] = Field(default_factory=list)
    npc_updates: list[_NpcUpdate] = Field(default_factory=list)
    npc_departures: list[str] = Field(default_factory=list)


def _empty_post() -> ScenePostOutput:
    return {
        "combat_ended": False,
        "scene_transition_push": None,
        "time_advance_hours": 0,
        "act_progress": False,
        "tension_delta": 0,
        "mood": None,
        "discovered": [],
        "threads_added": [],
        "threads_resolved": [],
        "npc_updates": [],
        "npc_departures": [],
    }


def _trigger(t: _CombatTrigger | None) -> CombatTrigger | None:
    return {"hostile_npc_ids": t.hostile_npc_ids} if t else None


def _transition(t: _SceneTransition | None) -> SceneTransition | None:
    return {"to_location_id": t.to_location_id, "reason": t.reason} if t else None


async def run_pre(context: dict) -> ScenePreOutput:
    # The nudge is deterministic scene-state math, not an LLM output — compute it first so it
    # survives even if the combat/transition LLM call parse-fails.
    nudge = compute_pacing_nudge(**context["pacing"])
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
        return {"combat_trigger": None, "scene_transition_pull": None, "pacing_nudge": nudge}

    return {
        "combat_trigger": _trigger(decision.combat_trigger),
        "scene_transition_pull": _transition(decision.scene_transition_pull),
        "pacing_nudge": nudge,
    }


def _post_output(decision: _PostDecision) -> ScenePostOutput:
    """Map the parsed decision to the output shape, dropping values the writers can't trust:
    an invalid mood, a time skip without a transition, and null NPC-update fields."""
    push = _transition(decision.scene_transition_push)
    hours = decision.time_advance_hours if push and decision.time_advance_hours > 0 else 0
    mood: SceneMood | None = decision.mood if decision.mood in _VALID_MOODS else None  # type: ignore[assignment]
    npc_updates: list[NpcPresence] = [
        {k: v for k, v in u.model_dump().items() if v is not None}  # type: ignore[misc]
        for u in decision.npc_updates
    ]
    return {
        "combat_ended": decision.combat_ended,
        "scene_transition_push": push,
        "time_advance_hours": hours,
        "act_progress": decision.act_progress,
        "tension_delta": decision.tension_delta,
        "mood": mood,
        "discovered": decision.discovered,
        "threads_added": decision.threads_added,
        "threads_resolved": decision.threads_resolved,
        "npc_updates": npc_updates,
        "npc_departures": decision.npc_departures,
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

    return _post_output(decision)
