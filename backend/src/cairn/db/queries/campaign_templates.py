import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.campaign_template import CampaignTemplate
from cairn.db.models.premade_character import PremadeCharacter
from cairn.domain.exceptions import NotFoundError


async def get_by_key(session: AsyncSession, key: str) -> CampaignTemplate | None:
    result = await session.execute(select(CampaignTemplate).where(CampaignTemplate.key == key))
    return result.scalar_one_or_none()


async def get(session: AsyncSession, template_id: uuid.UUID) -> CampaignTemplate:
    result = await session.execute(select(CampaignTemplate).where(CampaignTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if template is None:
        raise NotFoundError(f"campaign template {template_id} not found", code="template_not_found")
    return template


async def list_published(session: AsyncSession) -> list[CampaignTemplate]:
    result = await session.execute(
        select(CampaignTemplate).where(CampaignTemplate.status == "published").order_by(CampaignTemplate.title)
    )
    return list(result.scalars().all())


async def upsert(
    session: AsyncSession,
    *,
    world_id: uuid.UUID,
    key: str,
    title: str,
    premise: str,
    acts: list[dict[str, Any]],
    always_on_lore_keys: list[str],
    status: str,
) -> CampaignTemplate:
    stmt = (
        insert(CampaignTemplate)
        .values(
            world_id=world_id,
            key=key,
            title=title,
            premise=premise,
            acts=acts,
            always_on_lore_keys=always_on_lore_keys,
            status=status,
        )
        .on_conflict_do_update(
            constraint="uq_campaign_templates_key",
            set_={
                "world_id": world_id,
                "title": title,
                "premise": premise,
                "acts": acts,
                "always_on_lore_keys": always_on_lore_keys,
                "status": status,
            },
        )
        .returning(CampaignTemplate)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.scalar_one()


async def upsert_premade(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    key: str,
    sheet: dict[str, Any],
) -> PremadeCharacter:
    stmt = (
        insert(PremadeCharacter)
        .values(template_id=template_id, key=key, sheet=sheet)
        .on_conflict_do_update(
            constraint="uq_premade_characters_template_key",
            set_={"sheet": sheet},
        )
        .returning(PremadeCharacter)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.scalar_one()


async def list_premades(session: AsyncSession, template_id: uuid.UUID) -> list[PremadeCharacter]:
    result = await session.execute(
        select(PremadeCharacter).where(PremadeCharacter.template_id == template_id).order_by(PremadeCharacter.key)
    )
    return list(result.scalars().all())
