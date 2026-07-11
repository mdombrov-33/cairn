import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.session import Session
from cairn.db.models.world_bible_entry import WorldBibleEntry
from cairn.db.queries import campaign_templates as template_queries
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import turns as turn_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.db.queries import worlds as world_queries

log = structlog.get_logger()

DEFAULT_HOURS_PER_DAY = 24


async def _hours_per_day(db: AsyncSession, session: Session) -> int:
    """Read hours_per_day from the world calendar; default 24 if unset."""
    campaign = await campaign_queries.get_campaign(db, session.campaign_id)
    template = await template_queries.get(db, campaign.template_id)
    world = await world_queries.get(db, template.world_id)
    value = (world.calendar or {}).get("hours_per_day", DEFAULT_HOURS_PER_DAY)
    return int(value) if value else DEFAULT_HOURS_PER_DAY


def _build_day_summary(day_index: int, dm_responses: list[str]) -> str:
    """Assemble a day's summary from its turns.

    Provisional: concatenates the day's DM narration. Scene Director (next slice) will
    replace this with a scene-aware LLM summary once Scene.summary rows exist.
    """
    body = "\n\n".join(r.strip() for r in dm_responses if r and r.strip())
    if not body:
        return f"Day {day_index}: nothing of note was recorded."
    return body


async def maybe_roll_days(db: AsyncSession, session: Session) -> list[WorldBibleEntry]:
    """Write a DAY_SUMMARY entry for each in-game day that has newly elapsed.

    Called after any action that advances in_game_hours_elapsed (rests, travel, scene
    transitions). Idempotent: only rolls days strictly past last_day_summarized.
    """
    hours_per_day = await _hours_per_day(db, session)
    current_day = session.in_game_hours_elapsed // hours_per_day
    if current_day <= session.last_day_summarized:
        return []

    campaign = await campaign_queries.get_campaign(db, session.campaign_id)
    turns = await turn_queries.list_turns(db, session.id)
    dm_responses = [t.dm_response for t in turns if t.dm_response]

    written: list[WorldBibleEntry] = []
    for day_index in range(session.last_day_summarized + 1, current_day + 1):
        entry = await world_bible_queries.upsert_entry(
            db,
            campaign_id=campaign.id,
            namespace=campaign.world_bible_namespace,
            type_="DAY_SUMMARY",
            key=f"day_{day_index}",
            content=_build_day_summary(day_index, dm_responses),
            day_index=day_index,
        )
        written.append(entry)

    session.last_day_summarized = current_day
    await db.flush()
    log.info("days_rolled", session_id=str(session.id), through_day=current_day, count=len(written))
    return written
