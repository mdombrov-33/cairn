import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CreateCampaignRequest(BaseModel):
    name: str
    template_id: str


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: str
    name: str
    template_id: str
    world_bible_namespace: str
    created_at: datetime
