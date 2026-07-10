import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base
from cairn.types import AuthoredScene, NpcPresence


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    act_index: Mapped[int] = mapped_column(default=0, server_default="0")
    scene_mode: Mapped[str] = mapped_column(default="exploration", server_default="exploration")
    safety_level: Mapped[str] = mapped_column(default="safe", server_default="safe")
    summary: Mapped[str | None]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Scene depth + pacing (a scene is a layered situation). Authored content is
    # read-mostly; runtime state is written through the resolver + Scene Director
    # passes — never mid-stream tools. See cairn/types.py for the JSONB shapes.
    authored: Mapped[AuthoredScene] = mapped_column(JSONB, default=dict, server_default="{}")
    beat_count: Mapped[int] = mapped_column(default=0, server_default="0")
    tension_level: Mapped[int] = mapped_column(default=0, server_default="0")
    mood: Mapped[str] = mapped_column(default="quiet", server_default="quiet")
    last_revelation_at_turn: Mapped[int | None]
    discovered_facts: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    unresolved_threads: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    npcs_present: Mapped[list[NpcPresence]] = mapped_column(JSONB, default=list, server_default="[]")
    scene_progress_summary: Mapped[str | None]
