"""The MCP server: tool registration, protocol round-trip, HTTP mount."""
import json

from httpx import ASGITransport, AsyncClient
from mcp import Client

from grimoire.mcp.server import TOOL_NAMES, mcp_server

EXPECTED_TOOLS = {
    "search_library",
    "find_phrase",
    "search_pack",
    "get_product",
    "list_products",
    "get_page",
    "get_text",
    "list_monsters",
    "library_stats",
}


async def test_tools_registered_with_descriptions(mcp_sessions):
    async with Client(mcp_server) as client:
        listing = await client.list_tools()
        tools = {t.name: t for t in listing.tools}
        assert set(tools) == EXPECTED_TOOLS == set(TOOL_NAMES)
        for tool in tools.values():
            assert tool.description and len(tool.description) > 20, tool.name
        assert "matched_page" in client.instructions


async def test_tool_call_round_trip(db, library, mcp_sessions):
    async with Client(mcp_server) as client:
        result = await client.call_tool("library_stats", {})
        assert result.is_error is False
        payload = json.loads(result.content[0].text)
        assert payload["products"] == 4

        page = await client.call_tool(
            "get_page", {"product_id": library["sf1"].id, "page": 3}
        )
        assert "Kurabanda" in json.loads(page.content[0].text)["pages"][0]["markdown"]


async def test_tool_errors_reach_the_agent(mcp_sessions):
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_page", {"product_id": 424242, "page": 1})
        assert result.is_error is True
        assert "424242" in result.content[0].text


def _initialize_body(request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }


async def test_mounted_at_mcp_and_exempt_from_rate_limiting(monkeypatch):
    """One test, one session-manager run: the manager cannot be restarted."""
    from grimoire.config import settings
    from grimoire.main import app

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_requests", 1)

    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    async with mcp_server.session_manager.run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            statuses = []
            for i in range(3):
                resp = await c.post("/mcp", json=_initialize_body(i), headers=headers)
                statuses.append(resp.status_code)
            assert statuses == [200, 200, 200]
            assert resp.json()["result"]["serverInfo"]["name"] == "grimoire"


async def test_every_product_type_filter_documents_the_enum(mcp_sessions):
    # One description for all four tools, built from the enum so it can't drift.
    from grimoire.services.classification.enum import CODEX_PRODUCT_TYPES

    async with Client(mcp_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in ("search_library", "find_phrase", "search_pack", "list_products"):
        description = tools[name].input_schema["properties"]["product_type"].get("description", "")
        assert all(t in description for t in CODEX_PRODUCT_TYPES if t != "magazine"), name
