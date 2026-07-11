import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.sessions import RestRequest, SessionResponse
from cairn.application import rests as rest_service
from cairn.application import sessions as service
from cairn.sse.events import sse

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.get("/{session_id}", response_model=SessionResponse)
async def get(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> SessionResponse:
    session = await service.get(db, session_id=session_id, owner_id=user_id)
    return SessionResponse.model_validate(session)


@router.post("/{session_id}/short-rest")
async def short_rest(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
    body: RestRequest | None = None,
) -> StreamingResponse:
    return await _rest_response(
        db,
        session_id=session_id,
        owner_id=user_id,
        rest_type="short",
        confirm_risky=body.confirm_risky if body is not None else False,
    )


@router.post("/{session_id}/long-rest")
async def long_rest(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
    body: RestRequest | None = None,
) -> StreamingResponse:
    return await _rest_response(
        db,
        session_id=session_id,
        owner_id=user_id,
        rest_type="long",
        confirm_risky=body.confirm_risky if body is not None else False,
    )


async def _rest_response(
    db: DBSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
    rest_type: rest_service.RestType,
    confirm_risky: bool,
) -> StreamingResponse:
    prepared = await rest_service.prepare_rest(
        db,
        session_id=session_id,
        owner_id=owner_id,
        rest_type=rest_type,
        confirm_risky=confirm_risky,
    )

    async def generate() -> AsyncGenerator[str]:
        async for event in rest_service.stream(prepared):
            yield sse(event["type"], event["data"])

    return StreamingResponse(generate(), media_type="text/event-stream")
