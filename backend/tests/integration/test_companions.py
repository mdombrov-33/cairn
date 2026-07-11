"""Integration tests for adjust_approval — clamping, log trimming, mood, band crossings."""

import uuid

from httpx import AsyncClient

from cairn.application import companions
from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from tests._factories import DEFAULT_CHARACTER, make_campaign, make_character

_PROFILE = {"name": "Bram", "personality": "Loyal and blunt.", "voice": {"accent": "rough"}}


async def _make_companion(client: AsyncClient, campaign_id: str) -> uuid.UUID:
    comp = await make_character(
        client,
        campaign_id,
        **{**DEFAULT_CHARACTER, "name": "Bram", "is_companion": True, "narrative_profile": _PROFILE},
    )
    return uuid.UUID(comp["id"])


async def test_adjust_applies_delta_mood_and_band_crossing(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    cid = await _make_companion(client, camp["id"])

    async with db_client.get_session() as db:
        result = await companions.adjust_approval(
            db, character_id=cid, delta=20, reason="stood up for a stranger", turn_id=uuid.uuid4()
        )
        await db.commit()

    assert result["approval"] == 20
    assert result["mood"] == "inspired"  # a +20 swing reads as inspired
    assert result["crossed_thresholds"] == ["warming up"]  # neutral -> warming up


async def test_approval_clamps_to_bounds(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    cid = await _make_companion(client, camp["id"])

    async with db_client.get_session() as db:
        await companions.adjust_approval(db, character_id=cid, delta=100, reason="a", turn_id=uuid.uuid4())
        high = await companions.adjust_approval(db, character_id=cid, delta=50, reason="b", turn_id=uuid.uuid4())
        low = await companions.adjust_approval(db, character_id=cid, delta=-300, reason="c", turn_id=uuid.uuid4())
        await db.commit()

    assert high["approval"] == 100
    assert low["approval"] == -100


async def test_approval_log_trims_to_last_twenty(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    cid = await _make_companion(client, camp["id"])

    async with db_client.get_session() as db:
        for i in range(25):
            await companions.adjust_approval(db, character_id=cid, delta=1, reason=f"beat {i}", turn_id=uuid.uuid4())
        await db.commit()
        char = await character_queries.get_character(db, cid)

    assert char.companion_meta is not None
    log = char.companion_meta["approval_log"]
    assert len(log) == 20
    # The oldest five were dropped; the newest is last.
    assert log[-1]["reason"] == "beat 24"
    assert log[0]["reason"] == "beat 5"
