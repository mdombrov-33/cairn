import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.npc import NPC
from cairn.db.models.scene import Scene
from cairn.domain.exceptions import NotFoundError


async def create_npc(session: AsyncSession, *, campaign_id: uuid.UUID, **fields: Any) -> NPC:
    npc = NPC(campaign_id=campaign_id, **fields)
    session.add(npc)
    await session.flush()
    return npc


async def get_npcs_by_campaign(session: AsyncSession, campaign_id: uuid.UUID) -> list[NPC]:
    result = await session.execute(select(NPC).where(NPC.campaign_id == campaign_id).order_by(NPC.name))
    return list(result.scalars().all())


async def get_npc(session: AsyncSession, npc_id: uuid.UUID) -> NPC:
    result = await session.execute(select(NPC).where(NPC.id == npc_id))
    npc = result.scalar_one_or_none()
    if npc is None:
        raise NotFoundError(f"npc {npc_id} not found", code="npc_not_found")
    return npc


async def get_npc_for_campaign(session: AsyncSession, npc_id: uuid.UUID, campaign_id: uuid.UUID) -> NPC:
    result = await session.execute(select(NPC).where(NPC.id == npc_id, NPC.campaign_id == campaign_id))
    npc = result.scalar_one_or_none()
    if npc is None:
        raise NotFoundError(f"npc {npc_id} not found", code="npc_not_found")
    return npc


def _name_score(npc_name: str, hint: str) -> int:
    """Rank a name against a hint: exact > whole-word > substring > token-overlap > miss."""
    name = npc_name.lower()
    tokens = name.split()
    if name == hint:
        return 100
    if hint in tokens:
        return 80
    if hint in name or name in hint:
        return 50
    if set(hint.split()) & set(tokens):
        return 30
    return 0


async def find_by_name(
    session: AsyncSession,
    campaign_id: uuid.UUID,
    name_hint: str,
    *,
    location_id: uuid.UUID | None = None,
) -> NPC | None:
    """Best ranked match for a spoken name — exact beats partial, and an NPC standing in the
    current scene (``location_id``) wins ties over one referenced from elsewhere."""
    hint = name_hint.strip().lower()
    if not hint:
        return None
    npcs = await get_npcs_by_campaign(session, campaign_id)

    def rank(npc: NPC) -> int:
        score = _name_score(npc.name, hint)
        if score and location_id is not None and npc.location_id == location_id:
            score += 10
        return score

    best = max(npcs, key=rank, default=None)
    return best if best is not None and rank(best) > 0 else None


async def bump_dialogue_exchange(session: AsyncSession, npc: NPC) -> int:
    """Increment the promotion counter for a talked-to NPC; returns the new count."""
    npc.dialogue_exchange_count += 1
    await session.flush()
    return npc.dialogue_exchange_count


async def list_by_location(session: AsyncSession, campaign_id: uuid.UUID, location_id: uuid.UUID) -> list[NPC]:
    """Living NPCs at a location — the present cast for scene context."""
    result = await session.execute(
        select(NPC).where(NPC.campaign_id == campaign_id, NPC.location_id == location_id, NPC.hp > 0).order_by(NPC.name)
    )
    return list(result.scalars().all())


async def list_dead_in_scene(session: AsyncSession, scene_id: uuid.UUID) -> list[NPC]:
    """Dead NPCs (hp <= 0) at the scene's location — lootable corpses for search narration."""
    result = await session.execute(
        select(NPC)
        .join(Scene, (Scene.location_id == NPC.location_id) & (Scene.campaign_id == NPC.campaign_id))
        .where(Scene.id == scene_id, NPC.hp <= 0)
        .order_by(NPC.name)
    )
    return list(result.scalars().all())


async def update_disposition(session: AsyncSession, npc_id: uuid.UUID, disposition: str) -> NPC:
    npc = await get_npc(session, npc_id)
    npc.disposition = disposition
    await session.flush()
    return npc


async def delete_npc(session: AsyncSession, npc_id: uuid.UUID) -> None:
    """Retire an NPC row — used when a recruited NPC converts into a party Character."""
    npc = await get_npc(session, npc_id)
    await session.delete(npc)
    await session.flush()
