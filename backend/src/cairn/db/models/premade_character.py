import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base


class PremadeCharacter(Base):
    __tablename__ = "premade_characters"
    __table_args__ = (UniqueConstraint("template_id", "key", name="uq_premade_characters_template_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaign_templates.id", ondelete="CASCADE"), index=True)
    key: Mapped[str]
    # The full sheet payload — same shape as a CharacterCreate request body.
    # Cloned into a Character row when a player picks this premade.
    sheet: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
