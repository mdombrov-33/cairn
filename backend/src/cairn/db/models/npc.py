import uuid
from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base


class NPC(Base):
    __tablename__ = "npcs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), index=True)
    name: Mapped[str]
    bio: Mapped[str]
    personality: Mapped[str]
    voice_traits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
