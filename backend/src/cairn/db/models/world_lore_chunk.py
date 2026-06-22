import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base


class WorldLoreChunk(Base):
    __tablename__ = "world_lore_chunks"
    __table_args__ = (UniqueConstraint("world_id", "key", name="uq_world_lore_chunks_world_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(index=True)  # faction | region | deity | figure | history | custom
    key: Mapped[str]
    title: Mapped[str]
    content: Mapped[str]
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    always_on: Mapped[bool] = mapped_column(default=False, server_default="false")
    # populated by RAG embedder later; nullable so seed can write rows without embeddings.
    embedding: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
