import uuid

from fastapi import APIRouter, status

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.characters import (
    CharacterCreate,
    CharacterPatch,
    CharacterResponse,
    EquipRequest,
    GrantXpRequest,
    LevelUpPreviewResponse,
    LevelUpRequest,
    XpAwardResponse,
)
from cairn.domain.services import characters as service
from cairn.domain.services import equipment as equipment_service
from cairn.domain.services import leveling
from cairn.domain.services.leveling import LevelUpChoices

router = APIRouter(prefix="/v1/campaigns", tags=["characters"])


# Characters


@router.post(
    "/{campaign_id}/characters",
    response_model=CharacterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create(
    campaign_id: uuid.UUID,
    body: CharacterCreate,
    user_id: CurrentUserId,
    db: DBSession,
) -> CharacterResponse:
    character = await service.create(
        db,
        campaign_id=campaign_id,
        owner_id=user_id,
        body=body,
    )
    return CharacterResponse.model_validate(character)


@router.get("/{campaign_id}/characters", response_model=list[CharacterResponse])
async def list_characters(
    campaign_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> list[CharacterResponse]:
    characters = await service.list_for_campaign(db, campaign_id=campaign_id, owner_id=user_id)
    return [CharacterResponse.model_validate(c) for c in characters]


@router.patch("/{campaign_id}/characters/{character_id}", response_model=CharacterResponse)
async def patch(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    body: CharacterPatch,
    user_id: CurrentUserId,
    db: DBSession,
) -> CharacterResponse:
    character = await service.patch(
        db,
        character_id=character_id,
        campaign_id=campaign_id,
        owner_id=user_id,
        body=body,
    )
    return CharacterResponse.model_validate(character)


@router.delete(
    "/{campaign_id}/characters/{character_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> None:
    await service.delete(db, campaign_id=campaign_id, character_id=character_id, owner_id=user_id)


# Equipment


@router.post(
    "/{campaign_id}/characters/{character_id}/equip",
    response_model=CharacterResponse,
)
async def equip(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    body: EquipRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> CharacterResponse:
    character = await equipment_service.equip(
        db,
        character_id=character_id,
        campaign_id=campaign_id,
        owner_id=user_id,
        body=body,
    )
    return CharacterResponse.model_validate(character)


@router.post(
    "/{campaign_id}/characters/{character_id}/unequip",
    response_model=CharacterResponse,
)
async def unequip(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    body: EquipRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> CharacterResponse:
    character = await equipment_service.unequip(
        db,
        character_id=character_id,
        campaign_id=campaign_id,
        owner_id=user_id,
        body=body,
    )
    return CharacterResponse.model_validate(character)


# Leveling


@router.get(
    "/{campaign_id}/characters/{character_id}/level-up",
    response_model=LevelUpPreviewResponse,
)
async def level_up_preview(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> dict:
    return await leveling.get_level_up_preview(db, character_id=character_id, campaign_id=campaign_id, owner_id=user_id)


@router.post(
    "/{campaign_id}/characters/{character_id}/level-up",
    response_model=CharacterResponse,
)
async def level_up_apply(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    body: LevelUpRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> CharacterResponse:
    char = await leveling.apply_level_up(
        db,
        character_id=character_id,
        campaign_id=campaign_id,
        owner_id=user_id,
        choices=LevelUpChoices(
            hp_method=body.hp_method,
            hp_roll=body.hp_roll,
            asi=body.asi,
            feat=body.feat,
            feat_options=body.feat_options,
            new_spells=body.new_spells,
            subclass=body.subclass,
        ),
    )
    return CharacterResponse.model_validate(char)


@router.post(
    "/{campaign_id}/characters/{character_id}/grant-xp",
    response_model=XpAwardResponse,
)
async def grant_xp(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    body: GrantXpRequest,
    user_id: CurrentUserId,
    db: DBSession,
) -> dict:
    return await leveling.award_xp(
        db,
        character_id=character_id,
        campaign_id=campaign_id,
        owner_id=user_id,
        amount=body.amount,
    )
