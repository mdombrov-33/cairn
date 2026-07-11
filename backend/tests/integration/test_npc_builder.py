"""Integration tests for Phase 4 — lazy NPC building, world-cast instantiation, promotion.

The dialogue and builder *agents* (the LLM calls) are stubbed; these lock the wiring around
them: ranked / scene-aware name lookup, the on-miss fallback chain (authored world-cast
blueprint → generated background), and the ≥3-exchange auto-promotion with its deepen-pass.
"""

import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from cairn.agents.dialogue import DialogueResult
from cairn.application import npcs as npc_service
from cairn.db import client as db_client
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.domain.services.settings import ResolvedCampaignSettings
from cairn.pipelines.turn_graph import TurnState, _resolve_dialogue
from tests._factories import make_campaign, make_session

_MINI_PROFILE = {"name": "x", "personality": "y", "voice": {}}


def _state(session_id: str, campaign_id: str, npc_name: str) -> TurnState:
    return {
        "session_id": session_id,
        "campaign_id": campaign_id,
        "player_input": f"I talk to {npc_name}",
        "intent": "npc_dialogue",
        "npc_name": npc_name,
        "check": None,
        "npc_context": None,
        "rest_context": None,
        "scene_pre_output": None,
        "is_scene_entry": False,
        "combat_just_started": False,
        "settings": ResolvedCampaignSettings(),
    }


async def test_find_by_name_ranks_exact_over_partial(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    cid = uuid.UUID(camp["id"])
    async with db_client.get_session() as db:
        await npc_queries.create_npc(db, campaign_id=cid, name="Bexley", narrative_profile=_MINI_PROFILE)
        await npc_queries.create_npc(db, campaign_id=cid, name="Bex", narrative_profile=_MINI_PROFILE)
        await db.commit()

    async with db_client.get_session() as db:
        hit = await npc_queries.find_by_name(db, cid, "bex")
    assert hit is not None
    assert hit.name == "Bex"  # exact beats the substring match on "Bexley"


async def test_find_by_name_prefers_scene_local(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_session(client, camp["id"])  # starts the opening scene
    cid = uuid.UUID(camp["id"])
    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, cid)
        assert scene is not None and scene.location_id is not None
        here = await npc_queries.create_npc(
            db, campaign_id=cid, name="Warden", location_id=scene.location_id, narrative_profile=_MINI_PROFILE
        )
        await npc_queries.create_npc(db, campaign_id=cid, name="Warden", narrative_profile=_MINI_PROFILE)
        await db.commit()
        here_id = here.id
        location_id = scene.location_id

    async with db_client.get_session() as db:
        hit = await npc_queries.find_by_name(db, cid, "Warden", location_id=location_id)
    assert hit is not None
    assert hit.id == here_id  # the one standing in the current scene wins the tie


async def test_dialogue_miss_builds_background_npc(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    profile = {"name": "Tomkin", "personality": "Nervous, avoids eye contact.", "voice": {"accent": "reedy"}}

    with (
        patch("cairn.agents.npc_builder.build_background", new=AsyncMock(return_value=profile)) as mock_build,
        patch(
            "cairn.application.turns.resolvers.dialogue_agent.run",
            new=AsyncMock(return_value=DialogueResult(dialogue="Y-yes? What is it?")),
        ),
    ):
        out = await _resolve_dialogue(_state(sess["id"], camp["id"], "Tomkin"))

    assert out["npc_context"] == '[Tomkin]: "Y-yes? What is it?"'
    mock_build.assert_awaited_once()
    async with db_client.get_session() as db:
        npc = await npc_queries.find_by_name(db, uuid.UUID(camp["id"]), "Tomkin")
    assert npc is not None
    assert npc.tier == "background"
    assert npc.dialogue_exchange_count == 1  # this first exchange was counted


async def test_dialogue_miss_instantiates_world_cast_not_builder(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    with (
        patch("cairn.agents.npc_builder.build_background", new=AsyncMock()) as mock_build,
        patch(
            "cairn.application.turns.resolvers.dialogue_agent.run",
            new=AsyncMock(return_value=DialogueResult(dialogue="State your business.")),
        ),
    ):
        await _resolve_dialogue(_state(sess["id"], camp["id"], "Serel Vane"))

    mock_build.assert_not_awaited()  # an authored world figure is instantiated, never generated
    async with db_client.get_session() as db:
        npc = await npc_queries.find_by_name(db, uuid.UUID(camp["id"]), "Serel Vane")
    assert npc is not None
    assert npc.tier == "major"  # authored tier preserved through the clone
    assert str(npc.narrative_profile.get("profession", "")).startswith("Crowmarshal")


async def test_third_exchange_promotes_and_deepens(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    cid = uuid.UUID(camp["id"])
    async with db_client.get_session() as db:
        npc = await npc_queries.create_npc(
            db,
            campaign_id=cid,
            name="Pell",
            tier="background",
            narrative_profile={"name": "Pell", "personality": "Gruff.", "voice": {}},
        )
        await db.commit()
        npc_id = npc.id

    deepened = {
        "name": "Pell",
        "personality": "Gruff, and quietly grieving a son lost on the north road.",
        "voice": {"accent": "low"},
        "backstory": "Twenty years behind the same bar, and one grave he doesn't talk about.",
    }
    with patch("cairn.agents.npc_builder.deepen", new=AsyncMock(return_value=deepened)) as mock_deepen:
        for _ in range(npc_service.DIALOGUE_PROMOTION_THRESHOLD):
            async with db_client.get_session() as db:
                npc = await npc_queries.get_npc(db, npc_id)
                await npc_service.record_dialogue_exchange(db, npc=npc, scene=None)
                await db.commit()

    mock_deepen.assert_awaited_once()  # a single one-time deepen-pass at the threshold
    async with db_client.get_session() as db:
        npc = await npc_queries.get_npc(db, npc_id)
    assert npc.tier == "recurring"
    assert npc.dialogue_exchange_count == 3
    assert npc.narrative_profile.get("backstory")  # profile extended in place
