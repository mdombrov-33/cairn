import uuid

from fastapi import APIRouter, status

from cairn.api.deps import CurrentUserId, DBSession
from cairn.api.v1.schemas.characters import CharacterCreate, CharacterResponse
from cairn.domain.services import characters as service

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
        alignment=body.alignment,
        subclass=body.subclass,
        level=body.level,
        stats=body.stats,
        hp=body.hp,
        max_hp=body.max_hp,
        ac=body.ac,
        speed=body.speed,
        saving_throw_proficiencies=body.saving_throw_proficiencies,
        skill_proficiencies=body.skill_proficiencies,
        spellcasting_ability=body.spellcasting_ability,
        spell_slots=body.spell_slots,
        spells_known=body.spells_known,
        features=body.features,
        inventory=[item.model_dump() for item in body.inventory],
        currency=body.currency,
    )
    return CharacterResponse.model_validate(character)


@router.get("/{campaign_id}/characters", response_model=CharacterResponse)
async def get(
    campaign_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DBSession,
) -> CharacterResponse:
    character = await service.get_for_campaign(db, campaign_id=campaign_id, owner_id=user_id)
    return CharacterResponse.model_validate(character)
