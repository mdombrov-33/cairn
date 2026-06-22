import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cairn.agents import scene_narrator
from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.sessions import SessionResponse
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import ConflictError
from cairn.domain.services import rests as rest_service
from cairn.domain.services import sessions as service
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
) -> StreamingResponse:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, user_id)

    block_reason: str | None = None
    try:
        result = await rest_service.apply_short_rest(db, session_id=session_id)
        context = rest_service.build_rest_context("short", result)
    except ConflictError as e:
        result = {}
        context = rest_service.build_blocked_context(e.code)
        block_reason = e.code

    async def generate() -> AsyncGenerator[str]:
        if block_reason is None:
            yield sse("rest_applied", {"rest_type": "short", **result})
        else:
            yield sse("rest_blocked", {"reason": block_reason})
        async for chunk in scene_narrator.run("short rest", context=context):
            yield sse("token", {"text": chunk})
        yield sse("rest_end", {})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/{session_id}/long-rest")
async def long_rest(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> StreamingResponse:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, user_id)

    block_reason: str | None = None
    try:
        result = await rest_service.apply_long_rest(db, session_id=session_id)
        context = rest_service.build_rest_context("long", result)
    except ConflictError as e:
        result = {}
        context = rest_service.build_blocked_context(e.code)
        block_reason = e.code

    async def generate() -> AsyncGenerator[str]:
        if block_reason is None:
            yield sse("rest_applied", {"rest_type": "long", **result})
        else:
            yield sse("rest_blocked", {"reason": block_reason})
        async for chunk in scene_narrator.run("long rest", context=context):
            yield sse("token", {"text": chunk})
        yield sse("rest_end", {})

    return StreamingResponse(generate(), media_type="text/event-stream")
