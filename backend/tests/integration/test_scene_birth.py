"""Scene birth — authored content and NPC presence are layered onto a Scene at creation.

An authored location (the back room) yields a scene with the read-mostly `authored` blob,
authored scene_mode/safety, and `npcs_present` resolved to real NPC ids with merged agendas.
An unauthored location falls back to the location roster with an empty authored blob.
"""

import uuid

from httpx import AsyncClient

from cairn.db import client as db_client
from cairn.db.queries import locations as location_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.domain.services import narrative_context
from cairn.domain.services import scenes as scene_service
from tests._factories import make_campaign, make_session


async def _location_by_name(campaign_id: uuid.UUID, needle: str):
    async with db_client.get_session() as db:
        for loc in await location_queries.list_by_campaign(db, campaign_id):
            if needle in loc.name:
                return loc
    raise AssertionError(f"no location matching {needle!r}")


async def test_authored_location_births_layered_scene(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    campaign_id = uuid.UUID(camp["id"])
    back_room = await _location_by_name(campaign_id, "Back Room")

    async with db_client.get_session() as db:
        scene = await scene_service.open_scene(db, campaign_id=campaign_id, location=back_room, act_index=0)
        await db.commit()
        scene_id = scene.id
        grim = await npc_queries.find_by_name(db, campaign_id, "Old Grim")
        assert grim is not None

    async with db_client.get_session() as db:
        scene = await _reload(db, scene_id)

    # Authored buckets carried through; scene_mode/safety came from the authored YAML.
    assert scene.authored["surface_details"][0].startswith("A locked iron chest")
    assert scene.authored["hidden"][0]["reveals"].startswith("The writing desk has a false drawer")
    assert scene.scene_mode == "social"
    # Presence resolved authored names -> real NPC ids, with the merged in-scene agenda.
    grim_presence = next(p for p in scene.npcs_present if p["npc_id"] == str(grim.id))
    assert grim_presence["doing"].startswith("polishing")
    assert "midnight" in grim_presence["agenda"]


async def test_unauthored_location_births_thin_scene(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    campaign_id = uuid.UUID(camp["id"])
    main_room = await _location_by_name(campaign_id, "Main Room")

    async with db_client.get_session() as db:
        scene = await scene_service.open_scene(db, campaign_id=campaign_id, location=main_room, act_index=0)
        await db.commit()
        scene_id = scene.id

    async with db_client.get_session() as db:
        scene = await _reload(db, scene_id)

    assert scene.authored == {}
    assert scene.scene_mode == "exploration"  # default — main room has no authored scene
    assert isinstance(scene.npcs_present, list)  # roster fallback (empty until NPCs carry a location)


async def test_authored_scene_context_is_leak_proof(client: AsyncClient) -> None:
    """The narrator context surfaces the known bucket but never hidden reveals or locked secrets."""
    camp = await make_campaign(client)
    campaign_id = uuid.UUID(camp["id"])
    sess = await make_session(client, camp["id"])
    back_room = await _location_by_name(campaign_id, "Back Room")

    # Open the authored back room as the campaign's current scene (started latest → current).
    async with db_client.get_session() as db:
        await scene_service.open_scene(db, campaign_id=campaign_id, location=back_room, act_index=0)
        await db.commit()

    async with db_client.get_session() as db:
        context = await narrative_context.build_dm_context(db, uuid.UUID(sess["id"]))

    # Known bucket — atmosphere + surface details reach the narrator.
    assert "Lamplight" in context
    assert "A locked iron chest" in context
    # Hidden reveals are withheld; only a stub naming the check is present.
    assert "false drawer" not in context
    assert "footprints" not in context.lower()
    assert "Investigation" in context and "Perception" in context
    # Secret content stays out entirely — its unlock condition isn't in discovered_facts.
    assert "sealed letter" not in context
    # Present NPC carries its in-the-moment situational state.
    assert "Old Grim" in context
    assert "polishing" in context
    assert "midnight" in context


async def test_discovered_hidden_reveal_reaches_known_bucket(client: AsyncClient) -> None:
    """Once a hidden reveal is in discovered_facts, its stub is gone and the text is narratable."""
    camp = await make_campaign(client)
    campaign_id = uuid.UUID(camp["id"])
    sess = await make_session(client, camp["id"])
    back_room = await _location_by_name(campaign_id, "Back Room")

    async with db_client.get_session() as db:
        scene = await scene_service.open_scene(db, campaign_id=campaign_id, location=back_room, act_index=0)
        reveal = scene.authored["hidden"][0]["reveals"]  # the false-drawer reveal
        await scene_queries.mark_discovered(db, scene.id, reveal, turn_index=3)
        await db.commit()

    async with db_client.get_session() as db:
        context = await narrative_context.build_dm_context(db, uuid.UUID(sess["id"]))

    assert "false drawer" in context  # now earned → in the known bucket
    assert "Perception" in context  # the still-undiscovered detail keeps its stub


async def _reload(db, scene_id: uuid.UUID):
    return await scene_queries.get_scene(db, scene_id)
