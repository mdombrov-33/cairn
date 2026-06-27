import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.scene import Scene
from cairn.domain.exceptions import NotFoundError


async def create_scene(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    location_id: uuid.UUID | None,
    act_index: int = 0,
    scene_mode: str = "exploration",
    safety_level: str = "safe",
    summary: str | None = None,
) -> Scene:
    scene = Scene(
        campaign_id=campaign_id,
        location_id=location_id,
        act_index=act_index,
        scene_mode=scene_mode,
        safety_level=safety_level,
        summary=summary,
    )
    session.add(scene)
    await session.flush()
    return scene


async def get_scene(session: AsyncSession, scene_id: uuid.UUID) -> Scene:
    result = await session.execute(select(Scene).where(Scene.id == scene_id))
    scene = result.scalar_one_or_none()
    if scene is None:
        raise NotFoundError(f"scene {scene_id} not found", code="scene_not_found")
    return scene


async def get_current_scene(session: AsyncSession, campaign_id: uuid.UUID) -> Scene | None:
    """The campaign's open scene — most recently started, not yet ended."""
    result = await session.execute(
        select(Scene)
        .where(Scene.campaign_id == campaign_id, Scene.ended_at.is_(None))
        .order_by(Scene.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def close_scene(session: AsyncSession, scene_id: uuid.UUID, *, summary: str, ended_at: datetime) -> Scene:
    scene = await get_scene(session, scene_id)
    scene.summary = summary
    scene.ended_at = ended_at
    await session.flush()
    return scene
