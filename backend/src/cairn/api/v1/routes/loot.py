import uuid

from fastapi import APIRouter

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.loot import LootRequest, LootResponse
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.services import loot as loot_service

router = APIRouter(prefix="/v1/sessions", tags=["loot"])


@router.post("/{session_id}/loot", response_model=LootResponse)
async def loot(
    session_id: uuid.UUID,
    body: LootRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> LootResponse:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, user_id)

    item = await loot_service.loot_item(
        db,
        session_id=session_id,
        npc_id=body.npc_id,
        item_name=body.item_name,
        character_id=body.character_id,
    )
    return LootResponse(item=dict(item))
