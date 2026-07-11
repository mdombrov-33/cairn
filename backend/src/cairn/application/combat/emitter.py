import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.context import current_turn_id
from cairn.db.queries import turns as turn_queries
from cairn.domain.combat import TurnEvent

log = structlog.get_logger()


async def emit(db: AsyncSession, event: TurnEvent) -> None:
    turn_id = current_turn_id.get()
    if turn_id is None:
        # No recording_turn scope active (e.g. the standalone /rests route). Legitimate, but
        # observable: a dropped event here that the caller expected on a turn is a bug.
        log.debug("turn_event_dropped_no_scope", event_type=event.get("type"))
        return
    try:
        await turn_queries.append_event(db, turn_id, event)
    except Exception as exc:
        log.warning("turn_event_emit_failed", error=str(exc), event_type=event.get("type"))
