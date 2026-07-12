import json
import uuid
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import LATEST_PROTOCOL_VERSION, TextContent

from cairn.agents.zone_seeder import ZoneSeed
from cairn.api.mcp import build_mcp_server
from cairn.config import Settings, get_settings
from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.main import create_app
from cairn.tools.combat import start_combat
from tests._factories import make_campaign, make_character, make_session

TEST_ZONES: ZoneSeed = {
    "zones": [
        {
            "id": "center",
            "name": "Center",
            "description": "The middle of the room.",
            "cover": "none",
            "cover_ac_bonus": 0,
            "cover_save_bonus": 0,
            "difficult_terrain": False,
            "hazard": None,
            "distances": {},
        }
    ],
    "player_start": "center",
    "enemy_start": "center",
}


async def test_mcp_apply_damage_persists_stateful_tool_call(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    character = await make_character(client, campaign["id"])
    game_session = await make_session(client, campaign["id"])
    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=TEST_ZONES)):
        await start_combat.ainvoke({"session_id": game_session["id"], "enemies_json": "[]"})

    server = build_mcp_server()
    async with create_connected_server_and_client_session(server, raise_exceptions=True) as session:
        result = await session.call_tool(
            "apply_damage",
            {
                "session_id": game_session["id"],
                "combatant_id": character["id"],
                "combatant_type": "character",
                "amount": 3,
            },
        )

    assert result.isError is False
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text)["hp"] == character["hp"] - 3
    async with db_client.get_session() as db:
        persisted = await character_queries.get_character(db, uuid.UUID(character["id"]))
    assert persisted.hp == character["hp"] - 3


async def test_streamable_http_mount_lists_tools_with_lifespan() -> None:
    settings = Settings(
        database_url=get_settings().database_url,
        env="test",
        mcp_enabled=True,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8000",
            follow_redirects=True,
        ) as http,
    ):
        initialized = await http.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "cairn-tests", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200, initialized.text
        session_id = initialized.headers["Mcp-Session-Id"]
        listed = await http.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": session_id,
                "Mcp-Protocol-Version": LATEST_PROTOCOL_VERSION,
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )

    assert listed.status_code == 200
    assert len(listed.json()["result"]["tools"]) == 55


async def test_mcp_disabled_leaves_no_http_endpoint() -> None:
    settings = Settings(
        database_url=get_settings().database_url,
        env="test",
        mcp_enabled=False,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http:
        response = await http.post("/mcp", json={})

    assert response.status_code == 404
