import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base
from cairn.types import CombatState


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), index=True)
    current_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None]

    # Combat
    combat_active: Mapped[bool] = mapped_column(default=False, server_default="false")
    combat_state: Mapped[CombatState | None] = mapped_column(JSONB)

    in_game_hours_elapsed: Mapped[int] = mapped_column(default=0, server_default="0")
    last_day_summarized: Mapped[int] = mapped_column(default=0, server_default="0")

    # Seed for session_rng(). Tests pass a known seed for determinism; prod sessions
    # get a random int at creation. v1 does not persist runtime RNG state across rolls.
    rng_seed: Mapped[int] = mapped_column(default=0, server_default="0")
