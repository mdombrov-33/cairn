"""Companion approval subsystem.

Approval is an integer in [-100, 100] living in `Character.companion_meta`. It is
adjusted only by the post-turn `companion_reflector` pass (LLM-judged, in-character).
The raw integer is meta-info — never surfaced to the player; the player sees a vague
`approval_band` and the reasons in the approval log. `mood` is derived here, not stored
by the LLM: the standing sets a baseline, a recent large swing transiently overrides it.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.queries import characters as character_queries
from cairn.types import ApprovalLogEntry, CompanionMeta

APPROVAL_LOG_LIMIT = 20

# Player-facing vague standing. The raw number is never shown; this is.
_BANDS: list[tuple[int, str]] = [
    (70, "loyal"),
    (40, "friendly"),
    (15, "warming up"),
    (-14, "neutral"),
    (-39, "cold"),
    (-100, "hostile"),
]


def approval_band(approval: int) -> str:
    """Map raw approval to the vague band the player is allowed to see."""
    for threshold, label in _BANDS:
        if approval >= threshold:
            return label
    return "hostile"


def derive_mood(approval: int, recent_deltas: list[int]) -> str:
    """Deterministic mood: standing sets a baseline, a recent large swing overrides it."""
    if recent_deltas:
        if min(recent_deltas) <= -15:
            return "dejected" if approval <= -20 else "angry"
        if max(recent_deltas) >= 15:
            return "inspired"
    if approval >= 50:
        return "happy"
    if approval <= -40:
        return "dejected"
    if approval <= -15:
        return "upset"
    return "content"


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

    recent_deltas = [e["delta"] for e in log[-3:]]
    mood = derive_mood(total, recent_deltas)

    meta["approval"] = total
    meta["approval_log"] = log
    meta["mood"] = mood
    char.companion_meta = meta  # reassign so SQLAlchemy flags the JSONB column dirty
    await db.flush()

    crossed = [approval_band(total)] if approval_band(before) != approval_band(total) else []
    return {"approval": total, "mood": mood, "crossed_thresholds": crossed}
