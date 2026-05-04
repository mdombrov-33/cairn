import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WorldBibleEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    source_turn_id: uuid.UUID | None
    namespace: str
    type: str
    key: str
    content: str
    created_at: datetime
    updated_at: datetime
