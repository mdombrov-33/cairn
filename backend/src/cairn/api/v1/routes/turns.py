import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cairn.agents import scene_narrator
from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.turns import TurnResponse, SubmitTurnRequest
from cairn.db.queries import turns as turn_queries
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
    turn, intent = await service.prepare(
        db, session_id=session_id, owner_id=user_id, player_input=body.player_input
    )

    async def generate() -> AsyncGenerator[str, None]:
        yield sse("turn_start", {"turn_id": str(turn.id), "intent": intent})

        chunks: list[str] = []
        if intent == "narrative_action":
            async for chunk in scene_narrator.run(body.player_input):
                chunks.append(chunk)
                yield sse("token", {"text": chunk})

        dm_response = "".join(chunks)
        await turn_queries.update_turn_response(db, turn.id, dm_response=dm_response)

        yield sse("turn_end", {"turn_id": str(turn.id)})

    return StreamingResponse(generate(), media_type="text/event-stream", status_code=201)


@router.get("/{session_id}/turns", response_model=list[TurnResponse])
async def list_turns(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> list[TurnResponse]:
    turns = await service.list_turns(db, session_id=session_id, owner_id=user_id)
    return [TurnResponse.model_validate(t) for t in turns]


@router.get("/{session_id}/transcript", response_model=list[TurnResponse])
async def transcript(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> list[TurnResponse]:
    turns = await service.list_turns(db, session_id=session_id, owner_id=user_id)
    return [TurnResponse.model_validate(t) for t in turns]
