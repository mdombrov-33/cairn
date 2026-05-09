import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.characters import CharacterCreate, CharacterResponse
from cairn.domain.exceptions import AuthError, NotFoundError
from cairn.domain.services import characters as service


class CharacterPatch(BaseModel):
    name: str | None = None
    bio: str | None = None


router = APIRouter(prefix="/v1/campaigns", tags=["characters"])


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
        name=body.name,
        race=body.race,
        character_class=body.character_class,
        background=body.background,
        ability_scores=body.ability_scores,
        skill_choices=body.skill_choices,
        ac=body.ac,
        alignment=body.alignment,
        bio=body.bio,
        personality=body.personality,
        voice_traits=body.voice_traits,
        subrace=body.subrace,
        subclass=body.subclass,
        is_companion=body.is_companion,
        spell_choices=body.spell_choices,
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
    characters = await service.list_for_campaign(db, campaign_id=campaign_id, owner_id=user_id)
    character = next((c for c in characters if c.id == character_id), None)
    if character is None:
        raise NotFoundError(f"character {character_id} not found", code="character_not_found")
    if character.is_companion:
        raise AuthError("cannot modify companion characters", code="forbidden")

    if body.name is not None:
        character.name = body.name
    if body.bio is not None:
        character.bio = body.bio
    await db.flush()
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
