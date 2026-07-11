import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.application.turns.types import PendingTurnData
from cairn.db.base import Base
from cairn.domain.combat import TurnEvent


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), index=True)
    # Every turn belongs to a scene. Scene Director creates Scene rows on transitions and
    # sessions.start() eagerly creates the first scene, so this is always populated.
    scene_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int]
    player_input: Mapped[str]
    dm_response: Mapped[str | None]
    check_data: Mapped[PendingTurnData | None] = mapped_column(JSONB, nullable=True)
    # dice_rolls is reserved but currently unwritten by any service — leave loose.
    dice_rolls: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    events: Mapped[list[TurnEvent]] = mapped_column(JSONB, default=list)
    checkpoint_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
