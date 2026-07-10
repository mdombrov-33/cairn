import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class CreateCampaignRequest(BaseModel):
    name: str
    # Stable template key (e.g. "tavern_v1") — resolved to a CampaignTemplate row server-side.
    template_id: str


class PatchCampaignSettingsRequest(BaseModel):
    preset: str | None = None
    overrides: dict[str, Any] | None = None


class CampaignSettingsResponse(BaseModel):
    preset: str
    overrides: dict[str, Any]
    resolved: dict[str, Any]


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: str
    name: str
    template_id: uuid.UUID
    world_bible_namespace: str
    status: str
    current_act_index: int
    settings: dict[str, Any]
    member_ids: list[str]
    created_at: datetime
