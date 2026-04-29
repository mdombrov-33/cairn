import uuid

from fastapi import APIRouter

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.sessions import SessionResponse
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


@router.post("/{session_id}/end", response_model=SessionResponse)
async def end(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> SessionResponse:
    session = await service.end(db, session_id=session_id, owner_id=user_id)
    return SessionResponse.model_validate(session)
