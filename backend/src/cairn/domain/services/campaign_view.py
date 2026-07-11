"""Pure projections shared by campaign-scoped workflows."""

import uuid
from typing import Any


def act_at(template: Any, index: int) -> dict[str, Any] | None:
    """The act dict ``{title, premise, core_events}`` at ``index``, or None if out of range."""
    acts = template.acts or []
    if 0 <= index < len(acts):
        act = acts[index]
        return {
            "title": act.get("title", ""),
            "premise": act.get("premise", ""),
            "core_events": act.get("core_events") or [],
        }
    return None


def scene_turn_views(turns: list[Any], scene_id: uuid.UUID | None) -> list[dict[str, str]]:
    """Completed ``(player_input, dm_response)`` pairs, optionally restricted to one scene."""
    return [
        {"player_input": turn.player_input, "dm_response": turn.dm_response or ""}
        for turn in turns
        if turn.dm_response and (scene_id is None or turn.scene_id == scene_id)
    ]
