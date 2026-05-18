import uuid
from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    name: Mapped[str]
    description: Mapped[str]
    connections: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    zones: Mapped[list[Any]] = mapped_column(JSONB, default=list)
