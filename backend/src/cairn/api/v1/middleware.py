import uuid

from fastapi import Request

from cairn.api.deps import CurrentUserId, DBSession
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import ConflictError

# Methods that only read state — a frozen (dead) campaign stays fully viewable.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def require_active_campaign(request: Request, user_id: CurrentUserId, db: DBSession) -> None:
    """Reject mutating requests against a campaign whose status is `ended_dead` (hardcore death).

    Depends on auth so an unauthenticated request still 401s before this check. Resolves the
    campaign from `campaign_id` or `session_id` path params. Reads pass through.
    """
    if request.method in SAFE_METHODS:
        return

    params = request.path_params
    if "campaign_id" in params:
        campaign_id = uuid.UUID(str(params["campaign_id"]))
    elif "session_id" in params:
        db_session = await session_queries.get_session(db, uuid.UUID(str(params["session_id"])))
        campaign_id = db_session.campaign_id
    else:
        return

    campaign = await campaign_queries.get_campaign(db, campaign_id)
    if campaign.status == "ended_dead":
        raise ConflictError("campaign has ended in death", code="campaign_ended_dead")
