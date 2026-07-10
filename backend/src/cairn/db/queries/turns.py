import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.turn import Turn
from cairn.domain.exceptions import NotFoundError
from cairn.domain.services.settings import ResolvedCampaignSettings
from cairn.types import PendingTurnData, TurnEvent


async def create_turn(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    scene_id: uuid.UUID,
    idx: int,
    player_input: str,
) -> Turn:
    turn = Turn(session_id=session_id, scene_id=scene_id, idx=idx, player_input=player_input)
    session.add(turn)
    await session.flush()
    return turn


async def set_turn_scene(session: AsyncSession, turn_id: uuid.UUID, scene_id: uuid.UUID) -> None:
    turn = await get_turn(session, turn_id)
    turn.scene_id = scene_id
    await session.flush()


async def get_turn(session: AsyncSession, turn_id: uuid.UUID) -> Turn:
    result = await session.execute(select(Turn).where(Turn.id == turn_id))
    turn = result.scalar_one_or_none()
    if turn is None:
        raise NotFoundError(f"turn {turn_id} not found", code="turn_not_found")
    return turn


async def list_turns(session: AsyncSession, session_id: uuid.UUID) -> list[Turn]:
    result = await session.execute(select(Turn).where(Turn.session_id == session_id).order_by(Turn.idx))
    return list(result.scalars().all())


async def update_turn_response(
    session: AsyncSession,
    turn_id: uuid.UUID,
    *,
    dm_response: str,
    checkpoint_id: str | None = None,
) -> Turn:
    turn = await get_turn(session, turn_id)
    turn.dm_response = dm_response
    turn.checkpoint_id = checkpoint_id
    await session.flush()
    return turn


async def append_event(session: AsyncSession, turn_id: uuid.UUID, event: TurnEvent) -> None:
    turn = await get_turn(session, turn_id)
    turn.events = [*turn.events, event]


async def update_turn_check(
    session: AsyncSession,
    turn_id: uuid.UUID,
    *,
    check_data: PendingTurnData,
) -> Turn:
    turn = await get_turn(session, turn_id)
    serialized = dict(check_data)
    settings = serialized.get("settings")
    if isinstance(settings, ResolvedCampaignSettings):
        serialized["settings"] = settings.as_json()
    turn.check_data = cast(PendingTurnData, serialized)
    await session.flush()
    return turn
