"""Scene persistence workflows.

A scene is a *situation*. At birth we split a location's authored content into the
read-mostly `Scene.authored` blob and the runtime `npcs_present` list, resolving each
authored NPC reference (by name) to its real campaign NPC id. Unauthored locations fall
back to the location roster so a thin scene still knows who is standing in it.
"""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.location import Location
from cairn.db.models.scene import Scene
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.domain.services.scenes import split_authored
from cairn.types import AuthoredScene, NpcPresence

log = structlog.get_logger(__name__)


async def _resolve_authored_presence(
    db: AsyncSession, campaign_id: uuid.UUID, raw: dict[str, Any]
) -> list[NpcPresence]:
    """Merge authored `npcs_present` + `npc_agendas_in_scene` into runtime presence,
    resolving each NPC name to its campaign NPC id. Unresolvable references are dropped."""
    agendas: dict[str, str] = raw.get("npc_agendas_in_scene", {}) or {}
    presence: list[NpcPresence] = []
    for entry in raw.get("npcs_present", []) or []:
        name = entry.get("npc", "")
        npc = await npc_queries.find_by_name(db, campaign_id, name)
        if npc is None:
            log.warning("authored_npc_unresolved", name=name)
            continue
        item: NpcPresence = {"npc_id": str(npc.id)}
        if entry.get("doing"):
            item["doing"] = entry["doing"]
        if entry.get("attentive_to"):
            item["attentive_to"] = entry["attentive_to"]
        if name in agendas:
            item["agenda"] = agendas[name]
        presence.append(item)
    return presence


async def _roster_presence(db: AsyncSession, campaign_id: uuid.UUID, location_id: uuid.UUID) -> list[NpcPresence]:
    """Thin-scene fallback: everyone standing at the location, no authored situational state."""
    npcs = await npc_queries.list_by_location(db, campaign_id, location_id)
    return [{"npc_id": str(npc.id)} for npc in npcs]


async def open_scene(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    location: Location | None,
    act_index: int,
    default_scene_mode: str = "exploration",
    default_safety_level: str = "safe",
) -> Scene:
    """Create the scene for a location, layering in authored content when present.

    Authored `scene_mode` / `safety_level` win over the caller's defaults; NPC presence
    comes from the authored cast, or the location roster for a thin/unauthored scene.
    """
    raw: dict[str, Any] = location.authored_scene if location else {}
    authored: AuthoredScene
    if raw:
        authored = split_authored(raw)
        presence = await _resolve_authored_presence(db, campaign_id, raw)
        scene_mode = raw.get("scene_mode", default_scene_mode)
        safety_level = raw.get("safety_level", default_safety_level)
    else:
        authored = {}
        presence = await _roster_presence(db, campaign_id, location.id) if location else []
        scene_mode = default_scene_mode
        safety_level = default_safety_level

    return await scene_queries.create_scene(
        db,
        campaign_id=campaign_id,
        location_id=location.id if location else None,
        act_index=act_index,
        scene_mode=scene_mode,
        safety_level=safety_level,
        authored=authored,
        npcs_present=presence,
    )
