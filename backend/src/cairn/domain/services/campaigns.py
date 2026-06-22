import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.campaign import Campaign
from cairn.db.queries import campaign_templates as template_queries
from cairn.db.queries import campaigns as queries
from cairn.db.queries import locations as location_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.domain.exceptions import NotFoundError

if TYPE_CHECKING:
    from cairn.db.models.location import Location

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


async def _seed_locations(db: AsyncSession, campaign_id: uuid.UUID, template_id: str) -> list[Location]:
    path = _SEED_DIR / template_id / "locations.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text())
    locations = []
    for loc_data in data.get("locations", []):
        kwargs = {k: v for k, v in loc_data.items() if k != "id_slug"}
        location = await location_queries.create_location(db, campaign_id=campaign_id, **kwargs)
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
    # `template_id` from the request is the template's stable key (e.g. "tavern_v1").
    # The template must be seeded into the DB first (`make seed TEMPLATE=<key>`).
    template = await template_queries.get_by_key(db, template_id)
    if template is None:
        raise NotFoundError(f"campaign template {template_id!r} not found", code="template_not_found")

    campaign = await queries.create_campaign(
        db,
        owner_id=owner_id,
        name=name,
        template_id=template.id,
        world_bible_namespace=f"campaign_{uuid.uuid4().hex}",
    )
    # NPC/location blueprints still clone from the template's YAML files.
    await _seed_npcs(db, campaign.id, template.key)
    await _seed_locations(db, campaign.id, template.key)
    return campaign


async def advance_act(db: AsyncSession, *, campaign_id: uuid.UUID) -> Campaign:
    """Advance to the next act, or conclude the campaign if the final act is done.

    Explicit, auditable state transition — the mechanism. Scene Director (next slice)
    is the caller that decides *when* an act has been resolved; it invokes this.
    On conclusion: status -> "completed" and a CAMPAIGN_CONCLUDED world bible entry is
    written (campaign isolation means this can later echo into other campaigns as history).
    """
    campaign = await queries.get_campaign(db, campaign_id)
    template = await template_queries.get(db, campaign.template_id)
    num_acts = len(template.acts or [])
    next_index = campaign.current_act_index + 1

    if next_index >= num_acts:
        campaign.status = "completed"
        await world_bible_queries.upsert_entry(
            db,
            campaign_id=campaign.id,
            namespace=campaign.world_bible_namespace,
            type_="CAMPAIGN_CONCLUDED",
            key="campaign_concluded",
            content=f"The campaign '{campaign.name}' has concluded.",
        )
    else:
        campaign.current_act_index = next_index

    await db.flush()
    return campaign


async def get_starting_location(db: AsyncSession, campaign_id: uuid.UUID) -> Location | None:
    return await location_queries.get_first_for_campaign(db, campaign_id)


async def get(db: AsyncSession, *, campaign_id: uuid.UUID, owner_id: str) -> Campaign:
    return await queries.get_campaign_owned_by(db, campaign_id, owner_id)


async def list_(db: AsyncSession, *, owner_id: str) -> list[Campaign]:
    return await queries.list_campaigns_by_owner(db, owner_id)


async def delete(db: AsyncSession, *, campaign_id: uuid.UUID, owner_id: str) -> None:
    await queries.delete_campaign_owned_by(db, campaign_id, owner_id)
