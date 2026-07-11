import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SubmitTurnRequest(BaseModel):
    player_input: str


class ResolveRequest(BaseModel):
    roll: int = Field(ge=1, le=20)
    # Optional second d20 the client rolls when spending inspiration (advantage).
    inspiration_roll: int | None = Field(default=None, ge=1, le=20)
    use_inspiration: bool = False


class CompanionActionResolutionRequest(BaseModel):
    decision: Literal["confirm", "override"]
    override: str | None = None


class ReactionResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    checkpoint_id: str
    decision: Literal["take", "decline"]
    chosen_reaction: str | None = None

    @model_validator(mode="after")
    def validate_choice(self) -> ReactionResolutionRequest:
        if self.decision == "take" and self.chosen_reaction is None:
            raise ValueError("chosen_reaction is required when taking a reaction")
        if self.decision == "decline" and self.chosen_reaction is not None:
            raise ValueError("chosen_reaction must be null when declining a reaction")
        return self


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
