"""Unauthenticated Phase-A MCP projection.

This stateful server is for single-user local development only. Do not expose
it to the internet before Phase-B authentication is implemented.
"""

from mcp.server.fastmcp import FastMCP

from cairn.tools import registry


def build_mcp_server() -> FastMCP:
    """Project registered Cairn tools into one Streamable HTTP MCP server."""
    server = FastMCP(
        "cairn",
        instructions="Cairn's stateful tabletop engine. Local development only; authentication is not implemented.",
        json_response=True,
        streamable_http_path="/",
    )
    for registered in registry.mcp_tools():
        coroutine = registered.tool.coroutine
        if coroutine is None:
            raise TypeError(f"MCP tool {registered.tool.name!r} must be async")
        server.add_tool(
            coroutine,
            name=registered.tool.name,
            description=registered.tool.description,
        )
    return server
