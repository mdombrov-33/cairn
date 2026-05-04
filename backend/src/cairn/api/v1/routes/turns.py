import asyncio
import uuid
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cairn.agents import combat_resolver, lore_keeper, rules_lawyer, scene_narrator
from cairn.agents import npc_dialogue as npc_dialogue_agent
from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.turns import ResolveRequest, SubmitTurnRequest, TurnResponse
from cairn.db import client as db_client
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import turns as turn_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.domain.services import turns as service
from cairn.sse.events import sse

log = structlog.get_logger()

router = APIRouter(prefix="/v1/sessions", tags=["turns"])


async def _run_lore_keeper(
    dm_response: str,
    campaign_id: uuid.UUID,
    namespace: str,
    source_turn_id: uuid.UUID,
) -> None:
    try:
        entries = await lore_keeper.run(dm_response)
        if not entries:
            return
        async with db_client.get_sessionmaker()() as session, session.begin():
            for entry in entries:
                await world_bible_queries.upsert_entry(
                    session,
                    campaign_id=campaign_id,
                    namespace=namespace,
                    type_=entry.type,
                    key=entry.key,
                    content=entry.content,
                    source_turn_id=source_turn_id,
                )
        log.info("lore_keeper_done", count=len(entries), campaign_id=str(campaign_id))
    except Exception as exc:
        log.warning("lore_keeper_failed", error=str(exc), campaign_id=str(campaign_id))


@router.post("/{session_id}/turns")
async def submit(
    session_id: uuid.UUID,
    body: SubmitTurnRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> StreamingResponse:
    turn, intent, npc_name, campaign_id, namespace = await service.prepare(
        db, session_id=session_id, owner_id=user_id, player_input=body.player_input
    )

    async def generate() -> AsyncGenerator[str]:
        yield sse("turn_start", {"turn_id": str(turn.id), "intent": intent})

        chunks: list[str] = []

        if intent == "combat_action":
            async for chunk in combat_resolver.run(body.player_input, str(session_id)):
                chunks.append(chunk)
                yield sse("token", {"text": chunk})

            dm_response = "".join(chunks)
            await turn_queries.update_turn_response(db, turn.id, dm_response=dm_response)
            yield sse("turn_end", {"turn_id": str(turn.id)})
            asyncio.create_task(_run_lore_keeper(dm_response, campaign_id, namespace, turn.id))

        elif intent == "skill_check":
            check = await rules_lawyer.run(body.player_input)

            setup_chunks: list[str] = []
            async for chunk in scene_narrator.run(body.player_input):
                setup_chunks.append(chunk)
                yield sse("token", {"text": chunk})

            setup_prose = "".join(setup_chunks)
            check_data = {
                "skill": check.skill,
                "dc": check.dc,
                "modifier": check.modifier,
                "roll_type": check.roll_type,
                "status": "pending",
                "setup_prose": setup_prose,
            }
            await turn_queries.update_turn_check(db, turn.id, check_data=check_data)
            yield sse(
                "check_required",
                {
                    "skill": check.skill,
                    "dc": check.dc,
                    "modifier": check.modifier,
                    "roll_type": check.roll_type,
                },
            )

        elif intent == "npc_dialogue":
            npc = await npc_queries.find_by_name(db, campaign_id, npc_name or "")

            if npc is not None:
                result = await npc_dialogue_agent.run(body.player_input, npc)
                npc_context = f'[{npc.name}]: "{result.dialogue}"'
                if result.disposition_change:
                    await npc_queries.update_disposition(db, npc.id, result.disposition_change)
            else:
                npc_context = ""

            async for chunk in scene_narrator.run(body.player_input, context=npc_context):
                chunks.append(chunk)
                yield sse("token", {"text": chunk})

            dm_response = "".join(chunks)
            await turn_queries.update_turn_response(db, turn.id, dm_response=dm_response)
            yield sse("turn_end", {"turn_id": str(turn.id)})
            asyncio.create_task(_run_lore_keeper(dm_response, campaign_id, namespace, turn.id))

        else:  # narrative_action
            async for chunk in scene_narrator.run(body.player_input):
                chunks.append(chunk)
                yield sse("token", {"text": chunk})

            dm_response = "".join(chunks)
            await turn_queries.update_turn_response(db, turn.id, dm_response=dm_response)
            yield sse("turn_end", {"turn_id": str(turn.id)})
            asyncio.create_task(_run_lore_keeper(dm_response, campaign_id, namespace, turn.id))

    return StreamingResponse(generate(), media_type="text/event-stream", status_code=201)


@router.post("/{session_id}/turns/{turn_id}/resolve")
async def resolve(
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    body: ResolveRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> StreamingResponse:
    turn, check = await service.prepare_resolve(
        db, session_id=session_id, turn_id=turn_id, owner_id=user_id
    )
    campaign_id, namespace = await service.get_campaign_info(db, session_id=session_id)

    async def generate() -> AsyncGenerator[str]:
        total = body.roll + check["modifier"]
        success = total >= check["dc"]

        yield sse("roll_result", {"roll": body.roll, "total": total, "success": success})

        outcome_context = (
            f"[Skill Check] {check['skill'].title()} DC {check['dc']}: "
            f"rolled {body.roll} + {check['modifier']} = {total} — "
            f"{'SUCCESS' if success else 'FAILURE'}\n"
            f"Setup: {check['setup_prose']}"
        )
        outcome_chunks: list[str] = []
        async for chunk in scene_narrator.run(turn.player_input, context=outcome_context):
            outcome_chunks.append(chunk)
            yield sse("token", {"text": chunk})

        outcome_prose = "".join(outcome_chunks)
        dm_response = check["setup_prose"] + "\n\n" + outcome_prose
        resolved_check = {
            **check,
            "status": "resolved",
            "roll": body.roll,
            "total": total,
            "success": success,
        }
        await turn_queries.update_turn_response(db, turn.id, dm_response=dm_response)
        await turn_queries.update_turn_check(db, turn.id, check_data=resolved_check)

        yield sse("turn_end", {"turn_id": str(turn.id)})
        asyncio.create_task(_run_lore_keeper(dm_response, campaign_id, namespace, turn.id))

    return StreamingResponse(generate(), media_type="text/event-stream", status_code=200)


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
