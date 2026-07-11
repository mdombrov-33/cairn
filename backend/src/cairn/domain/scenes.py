"""Scene-owned JSONB shapes and Scene Director outputs."""

from typing import Literal, Required, TypedDict

SceneMood = Literal["quiet", "charged", "hostile", "intimate"]


class HiddenDetail(TypedDict):
    check: str
    dc: int
    reveals: str


class SceneSecret(TypedDict):
    unlocked_by: str | list[str]
    content: str


class SceneHook(TypedDict, total=False):
    hook: Required[str]
    to: str


class AuthoredScene(TypedDict, total=False):
    atmosphere: str
    surface_details: list[str]
    hidden: list[HiddenDetail]
    secrets: list[SceneSecret]
    threads_in_air: list[str]
    hooks_out: list[SceneHook]


class NpcPresence(TypedDict, total=False):
    npc_id: Required[str]
    doing: str
    attentive_to: list[str]
    agenda: str


class CombatTrigger(TypedDict):
    hostile_npc_ids: list[str]


class SceneTransition(TypedDict):
    to_location_id: str
    reason: str


class ScenePreOutput(TypedDict):
    combat_trigger: CombatTrigger | None
    scene_transition_pull: SceneTransition | None
    pacing_nudge: str | None


class ScenePostOutput(TypedDict):
    combat_ended: bool
    scene_transition_push: SceneTransition | None
    time_advance_hours: int
    act_progress: bool
    tension_delta: int
    mood: SceneMood | None
    discovered: list[str]
    threads_added: list[str]
    threads_resolved: list[str]
    npc_updates: list[NpcPresence]
    npc_departures: list[str]


PendingTransition = SceneTransition


class NarrativeRecovery(TypedDict):
    reason: str
    prior_events_summary: str
