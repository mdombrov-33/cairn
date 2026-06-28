"""Shared gather for campaign-scoped context.

The narrator's layered DM context and the Scene Director's routing context both walk
campaign → template → world, resolve the current act, and project in-scene turns — then
render the result differently (prose vs. routing dict). This module owns the gather; the two
callers own their renders. RAG over world lore and the world bible lands here later.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.campaign import Campaign
from cairn.db.models.campaign_template import CampaignTemplate
from cairn.db.models.turn import Turn
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


def act_at(template: CampaignTemplate, index: int) -> dict[str, Any] | None:
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


def scene_turn_views(turns: list[Turn], scene_id: uuid.UUID | None) -> list[dict[str, str]]:
    """Completed ``(player_input, dm_response)`` pairs, optionally restricted to one scene."""
    return [
        {"player_input": t.player_input, "dm_response": t.dm_response or ""}
        for t in turns
        if t.dm_response and (scene_id is None or t.scene_id == scene_id)
    ]
