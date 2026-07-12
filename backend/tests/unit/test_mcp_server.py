import json

from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent

from cairn.api.mcp import build_mcp_server
from cairn.tools import registry


async def test_mcp_server_projects_registry_and_calls_stateless_tool() -> None:
    server = build_mcp_server()

    async with create_connected_server_and_client_session(server, raise_exceptions=True) as session:
        listed = await session.list_tools()
        result = await session.call_tool("lookup_spell", {"name": "Fireball"})

    assert {tool.name for tool in listed.tools} == {registered.tool.name for registered in registry.mcp_tools()}
    assert len(listed.tools) == 55
    assert result.isError is False
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text)["name"] == "Fireball"
