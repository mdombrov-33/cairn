import uuid

from fastapi import APIRouter

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.npcs import NPCResponse
from cairn.domain.services import npcs as service

router = APIRouter(prefix="/v1/campaigns", tags=["npcs"])


@router.get("/{campaign_id}/npcs", response_model=list[NPCResponse])
async def list_npcs(
    campaign_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> list[NPCResponse]:
    npcs = await service.list_by_campaign(db, campaign_id=campaign_id, owner_id=user_id)
    return [NPCResponse.model_validate(n) for n in npcs]


@router.get("/{campaign_id}/npcs/{npc_id}", response_model=NPCResponse)
async def get_npc(
    campaign_id: uuid.UUID,
    npc_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> NPCResponse:
    npc = await service.get(db, campaign_id=campaign_id, npc_id=npc_id, owner_id=user_id)
    return NPCResponse.model_validate(npc)
