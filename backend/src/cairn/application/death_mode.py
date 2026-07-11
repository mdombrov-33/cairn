import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.character import Character
from cairn.db.models.session import Session
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import turns as turn_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.domain.services.combat.emitter import emit
from cairn.domain.services.settings import resolve_settings
from cairn.types import NarrativeRecovery

log = structlog.get_logger()


async def _recent_summary(db: AsyncSession, session: Session, *, limit: int = 3) -> str:
    """Stitch the last few DM responses into a short recap for the recovery narration."""
    turns = await turn_queries.list_turns(db, session.id)
    recent = [t.dm_response for t in turns if t.dm_response][-limit:]
    return "\n\n".join(r.strip() for r in recent) or "The battle is a blur."


async def resolve_pc_death(db: AsyncSession, session: Session, character: Character) -> None:
    """Apply the campaign's death mode to a fallen PC at combat end.

    Pacifist never reaches here — `apply_damage` clamps the PC's HP first.
    """
    campaign = await campaign_queries.get_campaign(db, session.campaign_id)
    mode = resolve_settings(campaign.settings).death_mode

    if mode == "hardcore":
        campaign.status = "ended_dead"
        await emit(db, {"type": "campaign_ended", "reason": "pc_death", "character": character.name})
        log.info("pc_death_hardcore", character_id=str(character.id), campaign_id=str(campaign.id))
        return

    # Narrative mode (default): the PC survives at the edge, with consequences.
    reason = f"{character.name} fell in battle but clung to life."
    summary = await _recent_summary(db, session)
    character.hp = 1
    character.status = "active"
    character.death_save_successes = 0
    character.death_save_failures = 0
    recovery: NarrativeRecovery = {"reason": reason, "prior_events_summary": summary}
    session.pending_recovery = recovery

    await world_bible_queries.upsert_entry(
        db,
        campaign_id=campaign.id,
        namespace=campaign.world_bible_namespace,
        type_="EVENT",
        key=f"near_death_{character.name.lower().replace(' ', '_')}",
        content=f"{character.name} was struck down in battle and barely survived. {reason}",
    )
    await emit(db, {"type": "pc_death_recovered", "character": character.name})
    log.info("pc_death_narrative", character_id=str(character.id), campaign_id=str(campaign.id))
