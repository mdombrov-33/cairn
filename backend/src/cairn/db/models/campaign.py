import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(index=True)
    name: Mapped[str]
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaign_templates.id", ondelete="RESTRICT"), index=True)
    world_bible_namespace: Mapped[str]
    status: Mapped[str] = mapped_column(default="active", server_default="active")
    current_act_index: Mapped[int] = mapped_column(default=0, server_default="0")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    member_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
