import uuid
from typing import Annotated

from cairn.application import inspiration as inspiration_service
from cairn.db import client as db_client
from cairn.tools.registry import register


@register(tags={"narrative", "mutation", "combat"})
async def grant_inspiration(
    character_id: Annotated[str, "The character's UUID."],
    reason: Annotated[str, "Short reason the inspiration was earned (clever play, dramatic roleplay)."],
) -> dict:
    """Award inspiration to a character for genuinely clever play or dramatic roleplay.

    Not for routine actions. Idempotent — inspiration does not stack.
    """
    async with db_client.get_session() as db:
        return await inspiration_service.grant(db, character_id=uuid.UUID(character_id), reason=reason)
