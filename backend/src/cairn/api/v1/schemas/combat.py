import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class MonsterEnemy(BaseModel):
    type: Literal["monster"]
    name: str
    count: int = 1


class NPCEnemy(BaseModel):
    type: Literal["npc"]
    id: uuid.UUID


CombatEnemy = Annotated[MonsterEnemy | NPCEnemy, Field(discriminator="type")]


class CombatStartRequest(BaseModel):
    enemies: list[CombatEnemy]


class CombatEndRequest(BaseModel):
    outcome: Literal["victory", "defeat", "retreat", "resolved"]


class CombatResponse(BaseModel):
    combat_active: bool
    combat_state: dict[str, Any] | None
