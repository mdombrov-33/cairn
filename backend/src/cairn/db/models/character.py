import uuid
from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn.db.base import Base


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), index=True)
    owner_id: Mapped[str] = mapped_column(index=True)
    name: Mapped[str]
    class_: Mapped[str] = mapped_column("class")
    level: Mapped[int] = mapped_column(default=1)
    hp: Mapped[int]
    max_hp: Mapped[int]
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    inventory: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
