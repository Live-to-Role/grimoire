"""The MCP server: tool registration and the ASGI app mounted at ``/mcp``.

Each tool is a thin wrapper that opens a session and delegates to the
``tools_*`` module, where the logic lives and is tested directly.
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from grimoire import __version__
from grimoire.mcp import tools_bestiary, tools_meta, tools_products, tools_search
from grimoire.mcp.common import ProductTypeFilter
from grimoire.mcp.db import open_session

INSTRUCTIONS = """Grimoire is the user's own tabletop RPG library: their PDFs, catalogued, \
with extracted text, search and a reviewed bestiary. Everything here is read-only.

Workflow: start with search_library for topics ("swamp hex-crawl for low levels") or \
find_phrase for names and exact terms ("Kurabanda"). When a hit has a matched_page, call \
get_page on it before quoting or summarising, because the snippet is only a fragment. A \
hit without one was matched on its title or metadata, or comes from a book extracted \
without page anchors; read it with get_text (get_product says whether it has page \
anchors). Prefer get_page whenever a page is known; get_text is for pageless books and \
for when one page is not enough. search_pack runs several phrasings at once and dedupes \
by product. Cite results as *Title, p. N*. library_stats says whether semantic search is \
available; if the mode is keyword_only, prefer exact terms and tell the user they can \
enable semantic search in Settings."""

mcp_server = MCPServer("grimoire", version=__version__, instructions=INSTRUCTIONS)


@mcp_server.tool()
async def search_library(
    query: str,
    limit: int = 10,
    game_system: str | None = None,
    product_type: ProductTypeFilter = None,
    level_min: int | None = None,
    level_max: int | None = None,
) -> dict:
    """Search the library by topic. Semantic plus keyword when semantic search is
    configured, keyword-only otherwise (the result says which). Each hit has a
    product_id, score, match_type, matched_page and snippet. game_system is an
    exact match; product_type takes any spelling of a type (see its description);
    level_min/level_max keep products whose level range overlaps. When matched_page
    is set, follow up with get_page(product_id, matched_page) before quoting; when
    it is null the hit matched on title or metadata, or the book has no page
    anchors, so read it with get_text."""
    async with open_session() as db:
        return await tools_search.search_library(
            db,
            query=query,
            limit=limit,
            game_system=game_system,
            product_type=product_type,
            level_min=level_min,
            level_max=level_max,
        )


@mcp_server.tool()
async def find_phrase(
    phrase: str,
    limit: int = 10,
    game_system: str | None = None,
    product_type: ProductTypeFilter = None,
) -> dict:
    """Find where the library's text says a specific thing: a monster, NPC, place
    or exact term. Keyword match over the full body text of every extracted
    book, best page per product. Use this for names; use search_library for
    topics. Returns product_id, title, page and a snippet."""
    async with open_session() as db:
        return await tools_search.find_phrase(
            db, phrase=phrase, limit=limit, game_system=game_system, product_type=product_type
        )


@mcp_server.tool()
async def search_pack(
    queries: list[str],
    limit_per_query: int = 10,
    global_limit: int | None = None,
    game_system: str | None = None,
    product_type: ProductTypeFilter = None,
) -> dict:
    """Run several phrasings of one question in a single call (at most 10) and
    merge the hits by product, keeping each product's best score and listing
    which queries matched it. Use when a topic has synonyms: swamp, marsh, bog."""
    async with open_session() as db:
        return await tools_search.search_pack(
            db,
            queries=queries,
            limit_per_query=limit_per_query,
            global_limit=global_limit,
            game_system=game_system,
            product_type=product_type,
        )


@mcp_server.tool()
async def get_product(product_id: int) -> dict:
    """Full catalogue metadata for one product: title, author, publisher, game
    system, type, level range, page count, description, tags, collections, and
    whether its text is extracted with page anchors (needed by get_page)."""
    async with open_session() as db:
        return await tools_products.get_product(db, product_id=product_id)


@mcp_server.tool()
async def list_products(
    query: str | None = None,
    game_system: str | None = None,
    product_type: ProductTypeFilter = None,
    publisher: str | None = None,
    tag: str | None = None,
    collection_id: int | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """Browse the catalogue. query matches title or file name (not contents; use
    search_library for that). product_type takes any spelling of a type; the
    other filters are exact, and tag is a tag name. Sorted
    by title, paginated with limit (max 100) and offset; total is the full count."""
    async with open_session() as db:
        return await tools_products.list_products(
            db,
            query=query,
            game_system=game_system,
            product_type=product_type,
            publisher=publisher,
            tag=tag,
            collection_id=collection_id,
            limit=limit,
            offset=offset,
        )


@mcp_server.tool()
async def get_page(product_id: int, page: int, context_pages: int = 0) -> dict:
    """The extracted markdown of one page of a product (1-based), optionally with
    up to 3 pages either side. This is the user's own extracted text. Total text
    is capped at 20,000 characters; truncated is set when the cap applied."""
    async with open_session() as db:
        return await tools_products.get_page(
            db, product_id=product_id, page=page, context_pages=context_pages
        )


@mcp_server.tool()
async def get_text(product_id: int, offset: int = 0, max_chars: int = 8000) -> dict:
    """A window of a product's full extracted markdown, from offset, at most
    max_chars (cap 20,000). next_offset is where to continue, or null at the
    end. Prefer get_page when you know the page; use this for legacy extractions
    without page anchors or to read through a short document."""
    async with open_session() as db:
        return await tools_products.get_text(
            db, product_id=product_id, offset=offset, max_chars=max_chars
        )


@mcp_server.tool()
async def list_monsters(
    environment: str | None = None,
    hd_min: float | None = None,
    hd_max: float | None = None,
    system_profile: str | None = None,
    product_id: int | None = None,
    name: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """Confirmed bestiary entries from the user's books, as pointers: name, book,
    page, hit dice, AC and environment tags. The stat block itself stays in the
    book; use get_page(product_id, page_number) to read it. system_profile is
    dcc or osr; hd_min/hd_max filter on hit dice; name is a substring match."""
    async with open_session() as db:
        return await tools_bestiary.list_monsters(
            db,
            environment=environment,
            hd_min=hd_min,
            hd_max=hd_max,
            system_profile=system_profile,
            product_id=product_id,
            name=name,
            limit=limit,
            offset=offset,
        )


@mcp_server.tool()
async def library_stats() -> dict:
    """Library size and health: product count, how many have extracted text and
    embeddings, confirmed bestiary entries, and whether search runs in hybrid
    (semantic plus keyword) or keyword_only mode. Call this first if a search
    comes back thin."""
    async with open_session() as db:
        return await tools_meta.library_stats(db)


TOOL_NAMES = (
    "search_library",
    "find_phrase",
    "search_pack",
    "get_product",
    "list_products",
    "get_page",
    "get_text",
    "list_monsters",
    "library_stats",
)

# Host checks are off to match the rest of the API, which has none: the MCP
# endpoint is exactly as reachable as /api/v1, no more and no less. The
# session manager this creates must be run for the app's lifetime; main.py's
# lifespan does that.
#
# The sub-app owns the "/mcp" path itself and main.py registers it with
# add_route, not mount: a Mount answers "/mcp" with a 307 to "/mcp/", and
# not every MCP client follows redirects on POST.
mcp_app = mcp_server.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
