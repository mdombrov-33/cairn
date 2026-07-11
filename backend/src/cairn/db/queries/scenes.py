import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.scene import Scene
from cairn.domain.exceptions import NotFoundError
from cairn.domain.scenes import AuthoredScene, NpcPresence, SceneMood


async def create_scene(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    location_id: uuid.UUID | None,
    act_index: int = 0,
    scene_mode: str = "exploration",
    safety_level: str = "safe",
    summary: str | None = None,
    authored: AuthoredScene | None = None,
    npcs_present: list[NpcPresence] | None = None,
) -> Scene:
    scene = Scene(
        campaign_id=campaign_id,
        location_id=location_id,
        act_index=act_index,
        scene_mode=scene_mode,
        safety_level=safety_level,
        summary=summary,
        authored=authored or {},
        npcs_present=npcs_present or [],
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


# --- Scene depth + pacing state writers -------------------------------------
# Service-applied only (skill-check resolver + the two Scene Director passes +
# mechanical beat count). Never LLM-callable tools. JSONB lists are reassigned
# (not mutated in place) so SQLAlchemy detects the change.


async def increment_beat_count(session: AsyncSession, scene_id: uuid.UUID) -> Scene:
    scene = await get_scene(session, scene_id)
    scene.beat_count += 1
    await session.flush()
    return scene


async def mark_discovered(session: AsyncSession, scene_id: uuid.UUID, fact: str, *, turn_index: int) -> Scene:
    """Add a newly discovered fact and stamp the revelation turn (for stalling detection)."""
    scene = await get_scene(session, scene_id)
    if fact not in scene.discovered_facts:
        scene.discovered_facts = [*scene.discovered_facts, fact]
        scene.last_revelation_at_turn = turn_index
        await session.flush()
    return scene


async def add_thread(session: AsyncSession, scene_id: uuid.UUID, thread: str) -> Scene:
    scene = await get_scene(session, scene_id)
    if thread not in scene.unresolved_threads:
        scene.unresolved_threads = [*scene.unresolved_threads, thread]
        await session.flush()
    return scene


async def resolve_thread(session: AsyncSession, scene_id: uuid.UUID, thread: str) -> Scene:
    scene = await get_scene(session, scene_id)
    if thread in scene.unresolved_threads:
        scene.unresolved_threads = [t for t in scene.unresolved_threads if t != thread]
        await session.flush()
    return scene


async def apply_tension(session: AsyncSession, scene_id: uuid.UUID, delta: int) -> Scene:
    scene = await get_scene(session, scene_id)
    scene.tension_level = max(0, min(10, scene.tension_level + delta))
    await session.flush()
    return scene


async def set_mood(session: AsyncSession, scene_id: uuid.UUID, mood: SceneMood) -> Scene:
    scene = await get_scene(session, scene_id)
    scene.mood = mood
    await session.flush()
    return scene


async def set_npcs_present(session: AsyncSession, scene_id: uuid.UUID, npcs_present: list[NpcPresence]) -> Scene:
    scene = await get_scene(session, scene_id)
    scene.npcs_present = npcs_present
    await session.flush()
    return scene


async def set_progress_summary(session: AsyncSession, scene_id: uuid.UUID, summary: str) -> Scene:
    scene = await get_scene(session, scene_id)
    scene.scene_progress_summary = summary
    await session.flush()
    return scene
