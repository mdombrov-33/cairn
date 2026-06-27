import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SubmitTurnRequest(BaseModel):
    player_input: str


class ResolveRequest(BaseModel):
    roll: int = Field(ge=1, le=20)
    # Optional second d20 the client rolls when spending inspiration (advantage).
    inspiration_roll: int | None = Field(default=None, ge=1, le=20)
    use_inspiration: bool = False


class TurnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    idx: int
    player_input: str
    dm_response: str | None
    check_data: dict[str, Any] | None
    dice_rolls: dict[str, Any]
    checkpoint_id: str | None
    events: list[Any]
    created_at: datetime
