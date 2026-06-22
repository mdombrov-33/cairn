import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.world import World
from cairn.db.models.world_lore_chunk import WorldLoreChunk
from cairn.domain.exceptions import NotFoundError


async def get_by_key(session: AsyncSession, key: str) -> World | None:
    result = await session.execute(select(World).where(World.key == key))
    return result.scalar_one_or_none()


async def get(session: AsyncSession, world_id: uuid.UUID) -> World:
    result = await session.execute(select(World).where(World.id == world_id))
    world = result.scalar_one_or_none()
    if world is None:
        raise NotFoundError(f"world {world_id} not found", code="world_not_found")
    return world


async def upsert(
    session: AsyncSession,
    *,
    key: str,
    name: str,
    summary: str | None,
    calendar: dict[str, Any],
) -> World:
    stmt = (
        insert(World)
        .values(key=key, name=name, summary=summary, calendar=calendar)
        .on_conflict_do_update(
            constraint="uq_worlds_key",
            set_={"name": name, "summary": summary, "calendar": calendar},
        )
        .returning(World)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.scalar_one()


async def upsert_lore_chunk(
    session: AsyncSession,
    *,
    world_id: uuid.UUID,
    category: str,
    key: str,
    title: str,
    content: str,
    tags: list[str],
    always_on: bool,
) -> WorldLoreChunk:
    stmt = (
        insert(WorldLoreChunk)
        .values(
            world_id=world_id,
            category=category,
            key=key,
            title=title,
            content=content,
            tags=tags,
            always_on=always_on,
        )
        .on_conflict_do_update(
            constraint="uq_world_lore_chunks_world_key",
            set_={"category": category, "title": title, "content": content, "tags": tags, "always_on": always_on},
        )
        .returning(WorldLoreChunk)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.scalar_one()


async def list_lore_chunks(
    session: AsyncSession,
    world_id: uuid.UUID,
    *,
    always_on_only: bool = False,
) -> list[WorldLoreChunk]:
    q = select(WorldLoreChunk).where(WorldLoreChunk.world_id == world_id)
    if always_on_only:
        q = q.where(WorldLoreChunk.always_on.is_(True))
    q = q.order_by(WorldLoreChunk.category, WorldLoreChunk.key)
    result = await session.execute(q)
    return list(result.scalars().all())
