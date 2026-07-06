from typing import Any

from cairn.api.v1.schemas.creatures import CreatureBase


class NPCResponse(CreatureBase):
    race: str | None
    background: str | None
    narrative_profile: dict[str, Any]
    disposition: str
    tier: str
    xp_value: int
