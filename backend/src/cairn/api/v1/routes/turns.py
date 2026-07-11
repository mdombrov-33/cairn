import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.turns import CompanionActionResolutionRequest, ResolveRequest, SubmitTurnRequest, TurnResponse
from cairn.application.turns import service
from cairn.application.turns.runtime import turn_runtime
from cairn.sse.events import sse

router = APIRouter(prefix="/v1/sessions", tags=["turns"])


@router.post("/{session_id}/turns")
async def submit(
    session_id: uuid.UUID,
    body: SubmitTurnRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> StreamingResponse:
    prepared = await turn_runtime.prepare(db, session_id=session_id, owner_id=user_id, player_input=body.player_input)

    async def generate() -> AsyncGenerator[str]:
        async for event in turn_runtime.continue_turn(db, prepared):
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
    resumption = await turn_runtime.prepare_check_resumption(
        db,
        session_id=session_id,
        turn_id=turn_id,
        owner_id=user_id,
        roll=body.roll,
        use_inspiration=body.use_inspiration,
        inspiration_roll=body.inspiration_roll,
    )

    async def generate() -> AsyncGenerator[str]:
        async for event in turn_runtime.resume_check(db, resumption):
            yield sse(event["type"], event["data"])

    return StreamingResponse(generate(), media_type="text/event-stream", status_code=200)


@router.post("/{session_id}/turns/{turn_id}/companion-action")
async def resolve_companion_action(
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    body: CompanionActionResolutionRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> StreamingResponse:
    resumption = await turn_runtime.prepare_companion_action_resumption(
        db,
        session_id=session_id,
        turn_id=turn_id,
        owner_id=user_id,
        decision=body.decision,
        override=body.override,
    )

    async def generate() -> AsyncGenerator[str]:
        async for event in turn_runtime.resume_companion_action(db, resumption):
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
