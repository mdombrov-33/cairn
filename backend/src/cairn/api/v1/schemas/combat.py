from typing import Any

from pydantic import BaseModel


class CombatResponse(BaseModel):
    combat_active: bool
    combat_state: dict[str, Any] | None
