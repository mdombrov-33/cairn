import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base


class WorldBibleEntry(Base):
    __tablename__ = "world_bible_entries"
    __table_args__ = (UniqueConstraint("campaign_id", "type", "key", name="uq_entry_campaign_type_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    source_turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"))
    namespace: Mapped[str] = mapped_column(index=True)
    type: Mapped[str]  # NPC | PLACE | EVENT | QUEST
    key: Mapped[str]
    content: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
