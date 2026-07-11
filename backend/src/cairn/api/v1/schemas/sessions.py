import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    current_location_id: uuid.UUID | None
    started_at: datetime
    ended_at: datetime | None
    summary: str | None
    combat_active: bool
    combat_state: dict[str, Any] | None
    in_game_hours_elapsed: int


class RestRequest(BaseModel):
    confirm_risky: bool = False
