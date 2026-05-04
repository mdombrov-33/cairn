import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.world_bible_entry import WorldBibleEntry


async def upsert_entry(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    namespace: str,
    type_: str,
    key: str,
    content: str,
    source_turn_id: uuid.UUID | None = None,
) -> WorldBibleEntry:
    stmt = (
        insert(WorldBibleEntry)
        .values(
            campaign_id=campaign_id,
            namespace=namespace,
            type=type_,
            key=key,
            content=content,
            source_turn_id=source_turn_id,
        )
        .on_conflict_do_update(
            constraint="uq_entry_campaign_type_key",
            set_={"content": content, "source_turn_id": source_turn_id},
        )
        .returning(WorldBibleEntry)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.scalar_one()


async def list_by_campaign(
    session: AsyncSession,
    campaign_id: uuid.UUID,
    type_: str | None = None,
) -> list[WorldBibleEntry]:
    q = select(WorldBibleEntry).where(WorldBibleEntry.campaign_id == campaign_id)
    if type_ is not None:
        q = q.where(WorldBibleEntry.type == type_)
    q = q.order_by(WorldBibleEntry.type, WorldBibleEntry.key)
    result = await session.execute(q)
    return list(result.scalars().all())
