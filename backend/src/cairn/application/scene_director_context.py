"""Assembles the context dicts the Scene Director's two passes render from.

Deliberately thin in this slice: name + disposition is enough to identify hostile
targets; mood/tension/companion-approval/world-bible RAG arrive in later slices.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.application import campaign_context
from cairn.db.models.scene import Scene
from cairn.db.models.session import Session
from cairn.db.queries import locations as location_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.domain.services import campaign_view

RECENT_TURNS_IN_SCENE = 5

# Combat events are everything except these meta event types, which the post-response
# pass must not mistake for combat activity.
_NON_COMBAT_EVENTS = frozenset(
    {"time_advanced", "inspiration_granted", "inspiration_spent", "pc_death_recovered", "campaign_ended"}
)

_TIME_OF_DAY = (
    (0.21, "deep night"),
    (0.33, "early morning"),
    (0.50, "morning"),
    (0.58, "midday"),
    (0.71, "afternoon"),
    (0.83, "evening"),
    (1.01, "night"),
)


async def _time_label(db: AsyncSession, session: Session) -> str:
    _, _, world = await campaign_context.world_chain(db, session.campaign_id)
    hours_per_day = int((world.calendar or {}).get("hours_per_day") or 24)

    day = session.in_game_hours_elapsed // hours_per_day + 1
    fraction = (session.in_game_hours_elapsed % hours_per_day) / hours_per_day
    label = next(name for cutoff, name in _TIME_OF_DAY if fraction < cutoff)
    return f"Day {day} in {world.name}, {label}"


async def _current_act(db: AsyncSession, campaign_id: uuid.UUID) -> dict[str, Any]:
    campaign, template, _ = await campaign_context.world_chain(db, campaign_id)
    return campaign_view.act_at(template, campaign.current_act_index) or {
        "title": "",
        "premise": "",
        "core_events": [],
    }


def _reachable_locations(connections: dict[str, Any]) -> list[dict[str, str]]:
    """Best-effort projection of Location.connections into {id, name, one_line}.

    Authored connection shapes vary (and are empty pre-launch); read defensively.
    """
    out: list[dict[str, str]] = []
    for key, val in (connections or {}).items():
        if isinstance(val, dict):
            out.append(
                {
                    "id": str(val.get("to") or key),
                    "name": str(val.get("name") or key),
                    "one_line": str(val.get("one_line") or ""),
                }
            )
        else:
            out.append({"id": str(key), "name": str(val), "one_line": ""})
    return out


async def build_pre_input_context(db: AsyncSession, session_id: uuid.UUID, player_input: str) -> dict[str, Any]:
    session = await session_queries.get_session(db, session_id)
    scene = await scene_queries.get_current_scene(db, session.campaign_id)

    location_name = "an unknown place"
    npcs_present: list[dict[str, str]] = []
    reachable: list[dict[str, str]] = []
    if scene is not None and scene.location_id is not None:
        location = await location_queries.get_location(db, scene.location_id)
        if location is not None:
            location_name = location.name
            reachable = _reachable_locations(location.connections)
        npcs = await npc_queries.list_by_location(db, session.campaign_id, scene.location_id)
        npcs_present = [
            {"id": str(n.id), "name": n.name, "role": n.class_ or "", "disposition": n.disposition} for n in npcs
        ]

    return {
        "player_input": player_input,
        "current_scene": {
            "location_name": location_name,
            "scene_mode": scene.scene_mode if scene else "exploration",
            "safety_level": scene.safety_level if scene else "safe",
            "authored_summary": scene.summary if scene else None,
            "npcs_present": npcs_present,
        },
        "reachable_locations": reachable,
        "combat_active": session.combat_active,
        "pending_transition": session.pending_transition is not None,
        "current_act": await _current_act(db, session.campaign_id),
        "session_time_label": await _time_label(db, session),
        "pacing": await _pacing_state(db, session_id, scene),
    }


async def _pacing_state(db: AsyncSession, session_id: uuid.UUID, scene: Scene | None) -> dict[str, Any]:
    """Scalars the deterministic pacing-nudge math reads. `turns_since_revelation` is the stall
    signal: turns elapsed since the last discovery, or the full beat count if nothing's been found."""
    if scene is None:
        return {"scene_mode": "exploration", "beat_count": 0, "tension_level": 0, "turns_since_revelation": 0}
    if scene.last_revelation_at_turn is None:
        turns_since = scene.beat_count
    else:
        turns = await turn_queries.list_turns(db, session_id)
        current_idx = max((t.idx for t in turns), default=0)
        turns_since = max(0, current_idx - scene.last_revelation_at_turn)
    return {
        "scene_mode": scene.scene_mode,
        "beat_count": scene.beat_count,
        "tension_level": scene.tension_level,
        "turns_since_revelation": turns_since,
    }


async def build_post_response_context(db: AsyncSession, session_id: uuid.UUID, turn_id: uuid.UUID) -> dict[str, Any]:
    session = await session_queries.get_session(db, session_id)
    turn = await turn_queries.get_turn(db, turn_id)
    scene = await scene_queries.get_current_scene(db, session.campaign_id)

    location_name = "an unknown place"
    if scene is not None and scene.location_id is not None:
        location = await location_queries.get_location(db, scene.location_id)
        if location is not None:
            location_name = location.name

    all_turns = await turn_queries.list_turns(db, session_id)
    scene_turns = campaign_view.scene_turn_views(all_turns, scene.id if scene else None)

    combat_events = [e for e in (turn.events or []) if e.get("type") not in _NON_COMBAT_EVENTS]

    return {
        "player_input": turn.player_input,
        "dm_response": turn.dm_response or "",
        "current_scene": {
            "location_name": location_name,
            "scene_mode": scene.scene_mode if scene else "exploration",
            "safety_level": scene.safety_level if scene else "safe",
        },
        "recent_turns": scene_turns[-RECENT_TURNS_IN_SCENE:],
        "combat_events_this_turn": combat_events,
        "current_act": await _current_act(db, session.campaign_id),
        "session_time_label": await _time_label(db, session),
    }
