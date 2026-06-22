import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base


class CampaignTemplate(Base):
    __tablename__ = "campaign_templates"
    __table_args__ = (UniqueConstraint("key", name="uq_campaign_templates_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("worlds.id", ondelete="RESTRICT"), index=True)
    key: Mapped[str] = mapped_column(index=True)  # stable slug; e.g. "tavern_v1"
    title: Mapped[str]
    premise: Mapped[str]
    # acts: [{title, premise, core_events: [str]}]
    acts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    always_on_lore_keys: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    status: Mapped[str] = mapped_column(default="draft", server_default="draft")  # draft | published
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
