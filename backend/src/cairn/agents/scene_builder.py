"""Scene builder — generates a layered scene for an unauthored location on demand.

Fired synchronously from the scene-transition resolver the first time the party enters a
location the world never wrote a scene for. Uses the stronger model tier (generation quality
shows here) and runs **once** per location: its output is persisted to `Location.authored_scene`,
so every later entry re-enters the authored path with no regeneration.

Output matches the raw authored-scene YAML shape (see `seed/.../scenes/*.yaml`) so scene birth
(`scenes.open_scene`) splits it into `Scene.authored` + `npcs_present` with no special-casing.
NPCs are only ever placed from the roster passed in — the builder never invents people. Parse-fail
safe: returns None so the caller falls back to a thin roster-only scene.
"""

from typing import Any

import structlog
from pydantic import BaseModel, Field

from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete_to_model
from cairn.llm.router import agent_setup

log = structlog.get_logger()


class _HiddenDetail(BaseModel):
    check: str
    dc: int
    reveals: str


class _Secret(BaseModel):
    unlocked_by: str
    content: str


class _Hook(BaseModel):
    hook: str
    to: str = ""


class _NpcInScene(BaseModel):
    npc: str
    doing: str = ""
    attentive_to: list[str] = Field(default_factory=list)
    agenda: str = ""


class _Scene(BaseModel):
    scene_mode: str = "exploration"
    safety_level: str = "safe"
    atmosphere: str
    surface_details: list[str] = Field(default_factory=list)
    hidden: list[_HiddenDetail] = Field(default_factory=list)
    secrets: list[_Secret] = Field(default_factory=list)
    threads_in_air: list[str] = Field(default_factory=list)
    hooks_out: list[_Hook] = Field(default_factory=list)
    npcs_present: list[_NpcInScene] = Field(default_factory=list)


def _to_raw(scene: _Scene, *, roster_names: set[str]) -> dict[str, Any]:
    """Map the parsed scene onto the raw authored-scene shape `open_scene` consumes.

    NPC presence and agendas are split the way the authored YAML splits them, and any NPC the
    model named outside the roster is dropped (the builder places people, it does not create them)."""
    present = [n for n in scene.npcs_present if n.npc in roster_names]
    raw: dict[str, Any] = {
        "scene_mode": scene.scene_mode,
        "safety_level": scene.safety_level,
        "atmosphere": scene.atmosphere,
        "surface_details": scene.surface_details,
        "hidden": [h.model_dump() for h in scene.hidden],
        "secrets": [s.model_dump() for s in scene.secrets],
        "threads_in_air": scene.threads_in_air,
        "hooks_out": [h.model_dump() for h in scene.hooks_out],
        "npcs_present": [{"npc": n.npc, "doing": n.doing, "attentive_to": n.attentive_to} for n in present],
        "npc_agendas_in_scene": {n.npc: n.agenda for n in present if n.agenda},
    }
    return raw


async def build(
    *,
    location_name: str,
    location_description: str,
    act_title: str,
    act_premise: str,
    time_label: str,
    roster: list[dict[str, str]],
) -> dict[str, Any] | None:
    """Generate a full layered scene for an unauthored location, or None if generation failed.

    `roster` is the NPCs standing at this location ({name, role, disposition}); the builder may
    place a subset of them into the scene with in-the-moment state, and nobody else.
    """
    prompt, model, fallbacks = agent_setup("scene_builder")
    roster_lines = "\n".join(f"- {n['name']} ({n.get('role') or 'local'}, {n['disposition']})" for n in roster)
    try:
        scene = await complete_to_model(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": prompt.render(
                        location_name=location_name,
                        location_description=location_description,
                        act_title=act_title,
                        act_premise=act_premise,
                        time_label=time_label,
                        roster=roster_lines,
                    ),
                }
            ],
            model_cls=_Scene,
            agent="scene_builder",
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
    except AgentError:
        log.warning("scene_builder_parse_failed", location=location_name)
        return None
    return _to_raw(scene, roster_names={n["name"] for n in roster})
