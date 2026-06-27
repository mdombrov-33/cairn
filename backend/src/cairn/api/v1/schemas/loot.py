import uuid
from typing import Any, Self

from pydantic import BaseModel, model_validator


class LootRequest(BaseModel):
    npc_id: uuid.UUID
    character_id: uuid.UUID
    item_name: str | None = None
    currency: dict[str, int] | None = None

    @model_validator(mode="after")
    def exactly_one_target(self) -> Self:
        if (self.item_name is None) == (self.currency is None):
            raise ValueError("provide exactly one of item_name or currency")
        return self


class LootResponse(BaseModel):
    item: dict[str, Any] | None = None
    currency: dict[str, int] | None = None
