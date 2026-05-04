import uuid

from fastapi import APIRouter

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.npcs import NPCResponse
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import npcs as npc_queries

router = APIRouter(prefix="/v1/campaigns", tags=["npcs"])


@router.get("/{campaign_id}/npcs", response_model=list[NPCResponse])
async def list_npcs(
    campaign_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> list[NPCResponse]:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, user_id)
    npcs = await npc_queries.get_npcs_by_campaign(db, campaign_id)
    return [NPCResponse.model_validate(n) for n in npcs]


@router.get("/{campaign_id}/npcs/{npc_id}", response_model=NPCResponse)
async def get_npc(
    campaign_id: uuid.UUID,
    npc_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> NPCResponse:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, user_id)
    npc = await npc_queries.get_npc(db, npc_id)
    return NPCResponse.model_validate(npc)
