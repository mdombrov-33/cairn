import uuid
from typing import Annotated

from langchain_core.tools import tool

from cairn.db import client as db_client
from cairn.domain.services import inspiration as inspiration_service


@tool
async def grant_inspiration(
    character_id: Annotated[str, "The character's UUID."],
    reason: Annotated[str, "Short reason the inspiration was earned (clever play, dramatic roleplay)."],
) -> dict:
    """Award inspiration to a character for genuinely clever play or dramatic roleplay.

    Not for routine actions. Idempotent — inspiration does not stack.
    """
    async with db_client.get_session() as db:
        return await inspiration_service.grant(db, character_id=uuid.UUID(character_id), reason=reason)
