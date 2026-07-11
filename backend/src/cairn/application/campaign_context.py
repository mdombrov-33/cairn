"""Campaign-scoped persistence gathers.

The narrator's layered DM context and the Scene Director's routing context both walk
campaign → template → world, resolve the current act, and project in-scene turns — then
render the result differently (prose vs. routing dict). This module owns the gather; the two
callers own their renders. RAG over world lore and the world bible lands here later.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.campaign import Campaign
from cairn.db.models.campaign_template import CampaignTemplate
from cairn.db.models.world import World
from cairn.db.queries import campaign_templates as template_queries
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import worlds as world_queries


async def world_chain(db: AsyncSession, campaign_id: uuid.UUID) -> tuple[Campaign, CampaignTemplate, World]:
    """Walk campaign → template → world in one place."""
    campaign = await campaign_queries.get_campaign(db, campaign_id)
    template = await template_queries.get(db, campaign.template_id)
    world = await world_queries.get(db, template.world_id)
    return campaign, template, world
