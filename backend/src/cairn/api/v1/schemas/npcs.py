from typing import Any

from cairn.api.v1.schemas.creatures import CreatureBase


class NPCResponse(CreatureBase):
    race: str | None
    background: str | None
    bio: str
    personality: str
    voice_traits: dict[str, Any]
    disposition: str
    xp_value: int
