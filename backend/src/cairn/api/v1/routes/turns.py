import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.turns import ResolveRequest, SubmitTurnRequest, TurnResponse
from cairn.domain.exceptions import ValidationError
from cairn.domain.services import inspiration as inspiration_service
from cairn.domain.services import turns as service
from cairn.sse.events import sse

router = APIRouter(prefix="/v1/sessions", tags=["turns"])


@router.post("/{session_id}/turns")
async def submit(
    session_id: uuid.UUID,
    body: SubmitTurnRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> StreamingResponse:
    turn, state, namespace = await service.prepare(
        db, session_id=session_id, owner_id=user_id, player_input=body.player_input
    )

    async def generate() -> AsyncGenerator[str]:
        async for event in service.stream(db, turn=turn, state=state, namespace=namespace):
            yield sse(event["type"], event["data"])

    return StreamingResponse(generate(), media_type="text/event-stream", status_code=201)


@router.post("/{session_id}/turns/{turn_id}/resolve")
async def resolve(
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    body: ResolveRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> StreamingResponse:
    turn, check = await service.prepare_resolve(db, session_id=session_id, turn_id=turn_id, owner_id=user_id)
    campaign_id, namespace = await service.get_campaign_info(db, session_id=session_id)
    active = await service.get_active_character(db, session_id=session_id)

    # Inspiration grants advantage: take the better of the two client-submitted d20s. The spend
    # happens here, before streaming starts, so a "no inspiration" rejection can surface as 422.
    effective_roll = body.roll
    advantage = False
    if body.use_inspiration:
        if active is None or not active.has_inspiration:
            raise ValidationError("character has no inspiration to spend", code="no_inspiration")
        await inspiration_service.spend(db, character_id=active.id)
        effective_roll = max(body.roll, body.inspiration_roll or body.roll)
        advantage = True

    async def generate() -> AsyncGenerator[str]:
        async for event in service.stream_resolve(
            db,
            turn=turn,
            check=check,
            active=active,
            effective_roll=effective_roll,
            advantage=advantage,
            raw_roll=body.roll,
            inspiration_roll=body.inspiration_roll,
            session_id=session_id,
            campaign_id=campaign_id,
            namespace=namespace,
        ):
            yield sse(event["type"], event["data"])

    return StreamingResponse(generate(), media_type="text/event-stream", status_code=200)


@router.get("/{session_id}/turns", response_model=list[TurnResponse])
async def list_turns(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> list[TurnResponse]:
    turns = await service.list_turns(db, session_id=session_id, owner_id=user_id)
    return [TurnResponse.model_validate(t) for t in turns]
