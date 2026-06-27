import uuid
from collections.abc import AsyncGenerator, AsyncIterator

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.agents import combat_resolver, scene_narrator
from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.turns import ResolveRequest, SubmitTurnRequest, TurnResponse
from cairn.context import current_turn_id
from cairn.db.models.turn import Turn
from cairn.domain.exceptions import ValidationError
from cairn.domain.services import inspiration as inspiration_service
from cairn.domain.services import narrative_context
from cairn.domain.services import turns as service
from cairn.sse.events import sse


def _join_context(*parts: str) -> str:
    return "\n\n".join(p for p in parts if p)


log = structlog.get_logger()

router = APIRouter(prefix="/v1/sessions", tags=["turns"])


async def _narrate(
    narrator: AsyncIterator[str],
    turn: Turn,
    db: AsyncSession,
    campaign_id: uuid.UUID,
    namespace: str,
) -> AsyncGenerator[str]:
    chunks: list[str] = []
    async for chunk in narrator:
        chunks.append(chunk)
        yield sse("token", {"text": chunk})

    dm_response = "".join(chunks)
    await service.save_turn_narrative(db, turn_id=turn.id, dm_response=dm_response)
    yield sse("turn_end", {"turn_id": str(turn.id)})
    service.schedule_lore_keeper(dm_response, campaign_id, namespace, turn.id)


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
    campaign_id = uuid.UUID(state["campaign_id"])
    intent = state["intent"]
    # Combat is resolved by the tool loop and rest has its own context block — neither
    # uses the layered DM context, so skip assembling it for those.
    dm_context = ""
    if intent not in ("combat_action", "rest_action"):
        dm_context = await narrative_context.build_dm_context(db, session_id)

    async def generate() -> AsyncGenerator[str]:
        token = current_turn_id.set(turn.id)
        try:
            yield sse("turn_start", {"turn_id": str(turn.id), "intent": intent})

            if intent == "combat_action":
                narrator = combat_resolver.run(body.player_input, str(session_id))
                async for event in _narrate(narrator, turn, db, campaign_id, namespace):
                    yield event

            elif intent == "skill_check":
                check = state["check"]
                assert check is not None
                setup_chunks: list[str] = []
                async for chunk in scene_narrator.run(body.player_input, context=dm_context):
                    setup_chunks.append(chunk)
                    yield sse("token", {"text": chunk})
                setup_prose = "".join(setup_chunks)
                await service.save_check_setup(db, turn_id=turn.id, check=check, setup_prose=setup_prose)
                check_payload: dict = {
                    "skill": check["skill"],
                    "dc": check["dc"],
                    "modifier": check["modifier"],
                    "roll_type": check["roll_type"],
                }
                helper = check.get("helper")
                if helper:
                    check_payload["helper"] = helper
                yield sse("check_required", check_payload)

            elif intent == "npc_dialogue":
                npc_context = state["npc_context"] or ""
                narrator = scene_narrator.run(body.player_input, context=_join_context(dm_context, npc_context))
                async for event in _narrate(narrator, turn, db, campaign_id, namespace):
                    yield event

            elif intent == "rest_action":
                # Rest context uses a special prefix the narrator keys on; keep it standalone.
                rest_ctx = state["rest_context"] or ""
                narrator = scene_narrator.run(body.player_input, context=rest_ctx)
                async for event in _narrate(narrator, turn, db, campaign_id, namespace):
                    yield event

            else:  # narrative_action
                narrator = scene_narrator.run(body.player_input, context=dm_context)
                async for event in _narrate(narrator, turn, db, campaign_id, namespace):
                    yield event
        finally:
            current_turn_id.reset(token)

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

    # Inspiration grants advantage: take the better of the two client-submitted d20s.
    effective_roll = body.roll
    advantage = False
    if body.use_inspiration:
        if active is None or not active.has_inspiration:
            raise ValidationError("character has no inspiration to spend", code="no_inspiration")
        await inspiration_service.spend(db, character_id=active.id)
        effective_roll = max(body.roll, body.inspiration_roll or body.roll)
        advantage = True

    async def generate() -> AsyncGenerator[str]:
        total = effective_roll + check["modifier"]
        success = total >= check["dc"]

        roll_payload: dict = {"roll": effective_roll, "total": total, "success": success}
        if advantage:
            roll_payload["advantage"] = True
            roll_payload["rolls"] = [body.roll, body.inspiration_roll or body.roll]
        helper = check.get("helper")
        if helper:
            roll_payload["helper"] = helper
        yield sse("roll_result", roll_payload)

        loot_intent = check.get("loot_intent")
        if loot_intent and active is not None:
            await service.resolve_pickpocket(
                db, session_id=session_id, loot_intent=loot_intent, character_id=active.id, success=success
            )

        # setup_prose is written by save_check_setup before this resolve runs.
        setup_prose = check.get("setup_prose", "")
        outcome_context = (
            f"[Skill Check] {check['skill'].title()} DC {check['dc']}: "
            f"rolled {body.roll} + {check['modifier']} = {total} — "
            f"{'SUCCESS' if success else 'FAILURE'}\n"
            f"Setup: {setup_prose}"
        )
        outcome_chunks: list[str] = []
        async for chunk in scene_narrator.run(turn.player_input, context=outcome_context):
            outcome_chunks.append(chunk)
            yield sse("token", {"text": chunk})

        outcome_prose = "".join(outcome_chunks)
        dm_response = setup_prose + "\n\n" + outcome_prose
        await service.save_resolved_check(
            db,
            turn_id=turn.id,
            check=check,
            roll=body.roll,
            total=total,
            success=success,
            dm_response=dm_response,
        )
        yield sse("turn_end", {"turn_id": str(turn.id)})
        service.schedule_lore_keeper(dm_response, campaign_id, namespace, turn.id)

    return StreamingResponse(generate(), media_type="text/event-stream", status_code=200)


@router.get("/{session_id}/turns", response_model=list[TurnResponse])
async def list_turns(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> list[TurnResponse]:
    turns = await service.list_turns(db, session_id=session_id, owner_id=user_id)
    return [TurnResponse.model_validate(t) for t in turns]
