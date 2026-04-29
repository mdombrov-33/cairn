import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class SubmitTurnRequest(BaseModel):
    player_input: str


class TurnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    idx: int
    player_input: str
    dm_response: str | None
    dice_rolls: dict[str, Any]
    checkpoint_id: str | None
    created_at: datetime
