from httpx import AsyncClient


async def _create_campaign(client: AsyncClient, user_id: str) -> dict:
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": user_id},
        json={"name": "Tavern", "template_id": "tavern_v1"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _start_session(client: AsyncClient, campaign_id: str, user_id: str) -> dict:
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/sessions",
        headers={"X-User-Id": user_id},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _submit_turn(
    client: AsyncClient, session_id: str, user_id: str, player_input: str
) -> dict:
    r = await client.post(
        f"/v1/sessions/{session_id}/turns",
        headers={"X-User-Id": user_id},
        json={"player_input": player_input},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_submit_turn_requires_auth(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    session = await _start_session(client, campaign["id"], "user_a")

    r = await client.post(
        f"/v1/sessions/{session['id']}/turns",
        json={"player_input": "I look around"},
    )
    assert r.status_code == 401


async def test_submit_turn_returns_turn(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    session = await _start_session(client, campaign["id"], "user_a")

    turn = await _submit_turn(client, session["id"], "user_a", "I look around the tavern")

    assert turn["session_id"] == session["id"]
    assert turn["player_input"] == "I look around the tavern"
    assert turn["idx"] == 0
    assert turn["dm_response"] is None
    assert turn["dice_rolls"] == {}


async def test_submit_turn_idx_increments(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    session = await _start_session(client, campaign["id"], "user_a")

    t0 = await _submit_turn(client, session["id"], "user_a", "I look around")
    t1 = await _submit_turn(client, session["id"], "user_a", "I talk to the bartender")
    t2 = await _submit_turn(client, session["id"], "user_a", "I ask about work")

    assert t0["idx"] == 0
    assert t1["idx"] == 1
    assert t2["idx"] == 2


async def test_submit_turn_wrong_owner_returns_404(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    session = await _start_session(client, campaign["id"], "user_a")

    r = await client.post(
        f"/v1/sessions/{session['id']}/turns",
        headers={"X-User-Id": "user_b"},
        json={"player_input": "I sneak in"},
    )
    assert r.status_code == 404


async def test_transcript_returns_turns_in_order(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    session = await _start_session(client, campaign["id"], "user_a")

    await _submit_turn(client, session["id"], "user_a", "First")
    await _submit_turn(client, session["id"], "user_a", "Second")
    await _submit_turn(client, session["id"], "user_a", "Third")

    r = await client.get(
        f"/v1/sessions/{session['id']}/transcript",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    turns = r.json()
    assert len(turns) == 3
    assert [t["player_input"] for t in turns] == ["First", "Second", "Third"]
    assert [t["idx"] for t in turns] == [0, 1, 2]


async def test_transcript_wrong_owner_returns_404(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    session = await _start_session(client, campaign["id"], "user_a")
    await _submit_turn(client, session["id"], "user_a", "Hello")

    r = await client.get(
        f"/v1/sessions/{session['id']}/transcript",
        headers={"X-User-Id": "user_b"},
    )
    assert r.status_code == 404


async def test_transcript_empty_before_any_turns(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    session = await _start_session(client, campaign["id"], "user_a")

    r = await client.get(
        f"/v1/sessions/{session['id']}/transcript",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    assert r.json() == []
