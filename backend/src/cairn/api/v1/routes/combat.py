import uuid

from fastapi import APIRouter, status

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.combat import CombatEndRequest, CombatResponse, CombatStartRequest
from cairn.domain.services import combat as service

router = APIRouter(prefix="/v1/sessions", tags=["combat"])


@router.post(
    "/{session_id}/combat/start", response_model=CombatResponse, status_code=status.HTTP_201_CREATED
)  # noqa: E501
async def start(
    session_id: uuid.UUID,
    body: CombatStartRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> CombatResponse:
    enemies = [e.model_dump() for e in body.enemies]
    combat_state = await service.start(db, session_id=session_id, owner_id=user_id, enemies=enemies)
    return CombatResponse(combat_active=True, combat_state=combat_state)


@router.post("/{session_id}/combat/end", response_model=CombatResponse)
async def end(
    session_id: uuid.UUID,
    body: CombatEndRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> CombatResponse:
    await service.end(db, session_id=session_id, owner_id=user_id, outcome=body.outcome)
    return CombatResponse(combat_active=False, combat_state=None)


@router.get("/{session_id}/combat", response_model=CombatResponse)
async def get_state(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> CombatResponse:
    state = await service.get_state(db, session_id=session_id, owner_id=user_id)
    return CombatResponse(**state)
