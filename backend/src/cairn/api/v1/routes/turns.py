import uuid

from fastapi import APIRouter

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.turns import SubmitTurnRequest, TurnResponse
from cairn.domain.services import turns as service

router = APIRouter(prefix="/v1/sessions", tags=["turns"])


@router.post("/{session_id}/turns", response_model=TurnResponse, status_code=201)
async def submit(
    session_id: uuid.UUID,
    body: SubmitTurnRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> TurnResponse:
    turn = await service.submit(
        db, session_id=session_id, owner_id=user_id, player_input=body.player_input
    )
    return TurnResponse.model_validate(turn)


@router.get("/{session_id}/transcript", response_model=list[TurnResponse])
async def transcript(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> list[TurnResponse]:
    turns = await service.transcript(db, session_id=session_id, owner_id=user_id)
    return [TurnResponse.model_validate(t) for t in turns]
