import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.queries import characters as character_queries
from cairn.domain.services.companions import approval_band, derive_mood
from cairn.types import ApprovalLogEntry, CompanionMeta

APPROVAL_LOG_LIMIT = 20


def _default_meta() -> CompanionMeta:
    return {"approval": 0, "mood": "content", "personal_goal": "", "secret": None, "approval_log": []}


async def adjust_approval(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    delta: int,
    reason: str,
    turn_id: uuid.UUID,
) -> dict:
    """Apply one approval delta: clamp to [-100, 100], append to the log (trim to last 20),
    recompute mood. Returns the new approval, mood, and any band boundary crossed."""
    char = await character_queries.get_character(db, character_id)
    meta: CompanionMeta = dict(char.companion_meta or _default_meta())  # type: ignore[assignment]

    before = meta.get("approval", 0)
    total = max(-100, min(100, before + delta))

    log: list[ApprovalLogEntry] = list(meta.get("approval_log", []))
    log.append({"turn_id": str(turn_id), "delta": delta, "reason": reason, "total": total})
    log = log[-APPROVAL_LOG_LIMIT:]

    mood = derive_mood(total, [entry["delta"] for entry in log[-3:]])
    meta["approval"] = total
    meta["approval_log"] = log
    meta["mood"] = mood
    char.companion_meta = meta
    await db.flush()

    crossed = [approval_band(total)] if approval_band(before) != approval_band(total) else []
    return {"approval": total, "mood": mood, "crossed_thresholds": crossed}
