import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base


class WorldBibleEntry(Base):
    __tablename__ = "world_bible_entries"
    __table_args__ = (UniqueConstraint("campaign_id", "type", "key", name="uq_entry_campaign_type_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    source_turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"))
    namespace: Mapped[str] = mapped_column(index=True)
    type: Mapped[str]  # NPC | PLACE | EVENT | QUEST | FACTION | RELATIONSHIP | DAY_SUMMARY | CAMPAIGN_CONCLUDED
    key: Mapped[str]
    content: Mapped[str]
    # Lore-book filter — players see entries only after the DM has actually mentioned them.
    revealed_at_turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"))
    # Calendar sidebar reads DAY_SUMMARY entries ordered by this column.
    day_index: Mapped[int | None] = mapped_column(nullable=True)
    # Populated by the RAG embedder; nullable until then.
    embedding: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
