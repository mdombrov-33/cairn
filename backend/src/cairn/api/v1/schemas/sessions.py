import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    summary: str | None
