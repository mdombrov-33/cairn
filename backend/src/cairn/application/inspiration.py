import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.application.combat.emitter import emit
from cairn.db.queries import characters as character_queries
from cairn.domain.exceptions import ConflictError

log = structlog.get_logger()


async def grant(db: AsyncSession, *, character_id: uuid.UUID, reason: str) -> dict:
    """Grant inspiration to a character. Idempotent — inspiration does not stack (PHB p. 125)."""
    char = await character_queries.get_character(db, character_id)
    already = char.has_inspiration
    char.has_inspiration = True
    await emit(db, {"type": "inspiration_granted", "character": char.name, "reason": reason})
    await db.commit()
    log.info("inspiration_granted", character_id=str(character_id), reason=reason)
    return {"character": char.name, "has_inspiration": True, "already_had": already}


async def spend(db: AsyncSession, *, character_id: uuid.UUID) -> dict:
    """Spend a character's inspiration. Raises ConflictError if they have none."""
    char = await character_queries.get_character(db, character_id)
    if not char.has_inspiration:
        raise ConflictError(f"{char.name} has no inspiration to spend", code="no_inspiration")
    char.has_inspiration = False
    await emit(db, {"type": "inspiration_spent", "character": char.name})
    await db.commit()
    log.info("inspiration_spent", character_id=str(character_id))
    return {"character": char.name, "has_inspiration": False}
