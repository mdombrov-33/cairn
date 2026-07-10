import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.campaign import Campaign
from cairn.db.queries import campaign_templates as template_queries
from cairn.db.queries import campaigns as queries
from cairn.db.queries import locations as location_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.db.queries import worlds as world_queries
from cairn.domain.exceptions import NotFoundError, ValidationError
from cairn.domain.services import settings as settings_service

if TYPE_CHECKING:
    from cairn.db.models.location import Location

_SEED_DIR = Path(__file__).parent.parent.parent / "seed" / "worlds"


async def _create_npc_from_yaml(db: AsyncSession, campaign_id: uuid.UUID, data: dict[str, Any]) -> None:
    kwargs = dict(data)
    kwargs.setdefault("hp", kwargs.get("max_hp", 1))
    if "class" in kwargs:
        kwargs["class_"] = kwargs.pop("class")
    await npc_queries.create_npc(db, campaign_id=campaign_id, **kwargs)


async def _seed_npcs(db: AsyncSession, campaign_id: uuid.UUID, campaign_dir: Path) -> None:
    """Clone the scenario's local cast (always present) into the campaign's NPC rows."""
    char_dir = campaign_dir / "characters"
    if not char_dir.exists():
        return
    for path in sorted(char_dir.glob("*.yaml")):
        await _create_npc_from_yaml(db, campaign_id, yaml.safe_load(path.read_text()))


async def _seed_world_cast(
    db: AsyncSession, campaign_id: uuid.UUID, world_dir: Path, character_keys: list[str]
) -> None:
    """Clone the world-cast figures this scenario explicitly connects. Unconnected world figures
    stay lore-only until lazily instantiated on-encounter (later slice)."""
    for key in character_keys:
        path = world_dir / "characters" / f"{key}.yaml"
        if not path.exists():
            continue
        await _create_npc_from_yaml(db, campaign_id, yaml.safe_load(path.read_text()))


def _load_authored_scenes(campaign_dir: Path) -> dict[str, dict[str, Any]]:
    """Authored scenes keyed by the location slug they belong to (`scenes/*.yaml`)."""
    scenes_dir = campaign_dir / "scenes"
    if not scenes_dir.exists():
        return {}
    by_location: dict[str, dict[str, Any]] = {}
    for path in sorted(scenes_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or {}
        scene = raw.get("scene", raw)  # authored files nest content under a `scene:` root
        loc_slug = scene.get("location_id")
        if loc_slug:
            by_location[loc_slug] = scene
    return by_location


async def _seed_locations(db: AsyncSession, campaign_id: uuid.UUID, campaign_dir: Path) -> list[Location]:
    path = campaign_dir / "locations.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text())
    authored_scenes = _load_authored_scenes(campaign_dir)
    locations = []
    for loc_data in data.get("locations", []):
        kwargs = {k: v for k, v in loc_data.items() if k != "id_slug"}
        kwargs["authored_scene"] = authored_scenes.get(loc_data["id_slug"], {})
        location = await location_queries.create_location(db, campaign_id=campaign_id, **kwargs)
        locations.append(location)
    await db.flush()
    return locations


async def create(
    db: AsyncSession,
    *,
    owner_id: str,
    name: str,
    template_id: str,
) -> Campaign:
    # `template_id` from the request is the template's stable key (e.g. "tavern_v1").
    # The template must be seeded into the DB first (`make seed TEMPLATE=<key>`).
    template = await template_queries.get_by_key(db, template_id)
    if template is None:
        raise NotFoundError(f"campaign template {template_id!r} not found", code="template_not_found")

    campaign = await queries.create_campaign(
        db,
        owner_id=owner_id,
        name=name,
        template_id=template.id,
        world_bible_namespace=f"campaign_{uuid.uuid4().hex}",
    )
    # Character/location blueprints clone from the world's YAML tree at creation:
    # the scenario's local cast always, plus the world-cast figures this scenario connects.
    world = await world_queries.get(db, template.world_id)
    world_dir = _SEED_DIR / world.key
    campaign_dir = world_dir / "campaigns" / template.key
    await _seed_npcs(db, campaign.id, campaign_dir)
    await _seed_world_cast(db, campaign.id, world_dir, template.world_characters)
    await _seed_locations(db, campaign.id, campaign_dir)
    return campaign


async def advance_act(db: AsyncSession, *, campaign_id: uuid.UUID) -> Campaign:
    """Advance to the next act, or conclude the campaign if the final act is done.

    Explicit, auditable state transition — the mechanism. Scene Director (next slice)
    is the caller that decides *when* an act has been resolved; it invokes this.
    On conclusion: status -> "completed" and a CAMPAIGN_CONCLUDED world bible entry is
    written (campaign isolation means this can later echo into other campaigns as history).
    """
    campaign = await queries.get_campaign(db, campaign_id)
    template = await template_queries.get(db, campaign.template_id)
    num_acts = len(template.acts or [])
    next_index = campaign.current_act_index + 1

    if next_index >= num_acts:
        campaign.status = "completed"
        await world_bible_queries.upsert_entry(
            db,
            campaign_id=campaign.id,
            namespace=campaign.world_bible_namespace,
            type_="CAMPAIGN_CONCLUDED",
            key="campaign_concluded",
            content=f"The campaign '{campaign.name}' has concluded.",
        )
    else:
        campaign.current_act_index = next_index

    await db.flush()
    return campaign


async def get_starting_location(db: AsyncSession, campaign_id: uuid.UUID) -> Location | None:
    return await location_queries.get_first_for_campaign(db, campaign_id)


async def get(db: AsyncSession, *, campaign_id: uuid.UUID, owner_id: str) -> Campaign:
    return await queries.get_campaign_owned_by(db, campaign_id, owner_id)


async def list_(db: AsyncSession, *, owner_id: str) -> list[Campaign]:
    return await queries.list_campaigns_by_owner(db, owner_id)


async def delete(db: AsyncSession, *, campaign_id: uuid.UUID, owner_id: str) -> None:
    await queries.delete_campaign_owned_by(db, campaign_id, owner_id)


async def get_settings(db: AsyncSession, *, campaign_id: uuid.UUID, owner_id: str) -> dict[str, Any]:
    campaign = await queries.get_campaign_owned_by(db, campaign_id, owner_id)
    stored = settings_service.parse_stored_settings(campaign.settings)
    return {
        "preset": stored.preset,
        "overrides": stored.overrides.as_json(),
        "resolved": settings_service.resolve_settings(stored).as_json(),
    }


async def update_settings(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    owner_id: str,
    preset: settings_service.CampaignPreset | None,
    overrides: settings_service.CampaignSettingsOverrides | None,
) -> dict[str, Any]:
    campaign = await queries.get_campaign_owned_by(db, campaign_id, owner_id)
    current = settings_service.parse_stored_settings(campaign.settings)
    next_preset = preset if preset is not None else current.preset

    next_overrides = current.overrides
    if overrides is not None:
        try:
            settings_service.validate_overrides(overrides)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        next_overrides = settings_service.merge_overrides(next_overrides, overrides)

    stored = settings_service.StoredCampaignSettings(preset=next_preset, overrides=next_overrides)
    campaign.settings = stored.as_json()
    await db.flush()
    return {
        "preset": next_preset,
        "overrides": next_overrides.as_json(),
        "resolved": settings_service.resolve_settings(stored).as_json(),
    }
