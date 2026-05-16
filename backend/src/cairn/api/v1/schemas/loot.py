import uuid
from typing import Any

from pydantic import BaseModel


class LootRequest(BaseModel):
    npc_id: uuid.UUID
    character_id: uuid.UUID
    item_name: str


class LootResponse(BaseModel):
    item: dict[str, Any]
