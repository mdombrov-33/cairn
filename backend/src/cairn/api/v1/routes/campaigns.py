import uuid

from fastapi import APIRouter, Query, status

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.campaigns import CampaignResponse, CreateCampaignRequest
from cairn.api.v1.schemas.lore import WorldBibleEntryResponse
from cairn.api.v1.schemas.sessions import SessionResponse
from cairn.domain.services import campaigns as service
from cairn.domain.services import lore as lore_service
from cairn.domain.services import sessions as session_service

router = APIRouter(prefix="/v1/campaigns", tags=["campaigns"])


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create(
    body: CreateCampaignRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> CampaignResponse:
    campaign = await service.create(
        db,
        owner_id=user_id,
        name=body.name,
        template_id=body.template_id,
    )
    return CampaignResponse.model_validate(campaign)


@router.get("", response_model=list[CampaignResponse])
async def list_(
    user_id: CurrentUserId,
    db: DBSession,
) -> list[CampaignResponse]:
    campaigns = await service.list_(db, owner_id=user_id)
    return [CampaignResponse.model_validate(c) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get(
    campaign_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> CampaignResponse:
    campaign = await service.get(db, campaign_id=campaign_id, owner_id=user_id)
    return CampaignResponse.model_validate(campaign)


@router.get("/{campaign_id}/lore", response_model=list[WorldBibleEntryResponse])
async def lore(
    campaign_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
    type: str | None = Query(None, description="Filter by world bible entry type"),
) -> list[WorldBibleEntryResponse]:
    entries = await lore_service.list_lore(db, campaign_id=campaign_id, owner_id=user_id, type_=type)
    return [WorldBibleEntryResponse.model_validate(e) for e in entries]


@router.get("/{campaign_id}/calendar", response_model=list[WorldBibleEntryResponse])
async def calendar(
    campaign_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> list[WorldBibleEntryResponse]:
    """Day summaries in calendar order — powers the calendar sidebar."""
    entries = await lore_service.list_calendar(db, campaign_id=campaign_id, owner_id=user_id)
    return [WorldBibleEntryResponse.model_validate(e) for e in entries]


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    campaign_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> None:
    await service.delete(db, campaign_id=campaign_id, owner_id=user_id)


@router.post(
    "/{campaign_id}/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_session(
    campaign_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> SessionResponse:
    session = await session_service.start(db, campaign_id=campaign_id, owner_id=user_id)
    return SessionResponse.model_validate(session)
