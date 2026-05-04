import uuid
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.campaign import Campaign
from cairn.db.models.location import Location
from cairn.db.queries import campaigns as queries
from cairn.db.queries import npcs as npc_queries

_SEED_DIR = Path(__file__).parent.parent.parent / "seed" / "templates"


async def _seed_npcs(db: AsyncSession, campaign_id: uuid.UUID, template_id: str) -> None:
    path = _SEED_DIR / template_id / "npcs.yaml"
    if not path.exists():
        return
    data = yaml.safe_load(path.read_text())
    for npc_data in data.get("npcs", []):
        kwargs = dict(npc_data)
        kwargs.setdefault("hp", kwargs.get("max_hp", 1))
        if "class" in kwargs:
            kwargs["class_"] = kwargs.pop("class")
        await npc_queries.create_npc(db, campaign_id=campaign_id, **kwargs)


async def _seed_locations(
    db: AsyncSession, campaign_id: uuid.UUID, template_id: str
) -> list[Location]:
    path = _SEED_DIR / template_id / "locations.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text())
    locations = []
    for loc_data in data.get("locations", []):
        kwargs = {k: v for k, v in loc_data.items() if k != "id_slug"}
        location = Location(campaign_id=campaign_id, **kwargs)
        db.add(location)
        locations.append(location)
    await db.flush()
    return locations


async def create(
    db: AsyncSession,
    *,
    owner_id: str,
    name: str,
    template_id: str,
) -> Campaign:
    campaign = await queries.create_campaign(
        db,
        owner_id=owner_id,
        name=name,
        template_id=template_id,
        world_bible_namespace=f"campaign_{uuid.uuid4().hex}",
    )
    await _seed_npcs(db, campaign.id, template_id)
    await _seed_locations(db, campaign.id, template_id)
    return campaign


async def get_starting_location(db: AsyncSession, campaign_id: uuid.UUID) -> Location | None:
    from sqlalchemy import select

    result = await db.execute(select(Location).where(Location.campaign_id == campaign_id).limit(1))
    return result.scalar_one_or_none()


async def get(db: AsyncSession, *, campaign_id: uuid.UUID, owner_id: str) -> Campaign:
    return await queries.get_campaign_owned_by(db, campaign_id, owner_id)


async def list_(db: AsyncSession, *, owner_id: str) -> list[Campaign]:
    return await queries.list_campaigns_by_owner(db, owner_id)


async def delete(db: AsyncSession, *, campaign_id: uuid.UUID, owner_id: str) -> None:
    await queries.delete_campaign_owned_by(db, campaign_id, owner_id)
