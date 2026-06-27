import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.session import Session
from cairn.domain.services import day_roll
from cairn.domain.services.combat.emitter import emit

log = structlog.get_logger()


async def advance_time(db: AsyncSession, session: Session, *, hours: int, source: str) -> None:
    """Single writer for in-game time. Advances the clock, records a turn event, rolls days.

    Emits `time_advanced` onto the current turn (via the combat emitter — no-ops when no
    turn is in scope, e.g. the standalone rest route). The post-response Scene Director pass
    reads this event to avoid double-counting a DM-narrated time skip on top of a rest.
    """
    if hours <= 0:
        return
    session.in_game_hours_elapsed += hours
    await emit(db, {"type": "time_advanced", "source": source, "hours": hours})
    await day_roll.maybe_roll_days(db, session)
    log.info("time_advanced", session_id=str(session.id), hours=hours, source=source)
