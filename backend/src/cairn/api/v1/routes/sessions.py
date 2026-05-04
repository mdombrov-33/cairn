import uuid

from fastapi import APIRouter, Query

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.lore import WorldBibleEntryResponse
from cairn.api.v1.schemas.sessions import SessionResponse
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.domain.services import sessions as service

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.get("/{session_id}", response_model=SessionResponse)
async def get(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> SessionResponse:
    session = await service.get(db, session_id=session_id, owner_id=user_id)
    return SessionResponse.model_validate(session)


@router.get("/{session_id}/lore", response_model=list[WorldBibleEntryResponse])
async def lore(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
    type: str | None = Query(None, description="Filter by type: NPC, PLACE, EVENT, QUEST"),
) -> list[WorldBibleEntryResponse]:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, user_id)
    entries = await world_bible_queries.list_by_campaign(db, db_session.campaign_id, type_=type)
    return [WorldBibleEntryResponse.model_validate(e) for e in entries]


@router.post("/{session_id}/end", response_model=SessionResponse)
async def end(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> SessionResponse:
    session = await service.end(db, session_id=session_id, owner_id=user_id)
    return SessionResponse.model_validate(session)
