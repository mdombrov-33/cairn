import uuid

from fastapi import APIRouter

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.combat import CombatResponse
from cairn.application.combat import state as service

# Combat is started and ended inside the turn graph (Scene Director → combat_entry) and by the
# combat resolver's end_combat tool. This router exposes only the read endpoint for the UI tracker.
router = APIRouter(prefix="/v1/sessions", tags=["combat"])


@router.get("/{session_id}/combat", response_model=CombatResponse)
async def get_state(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> CombatResponse:
    state = await service.get_state(db, session_id=session_id, owner_id=user_id)
    return CombatResponse(**state)
