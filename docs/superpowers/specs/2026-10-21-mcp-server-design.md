# MCP Server — Design Spec

**Date:** 2026-10-21
**Status:** Approved 2026-10-21; implemented the same day. Corrections found during implementation are marked ⚠️ inline.
**Scope:** Read-only agent access to the library over the Model Context Protocol
**Origin:** Comparison against [joelhooks/pdf-brain](https://github.com/joelhooks/pdf-brain);
the other borrowings from that review are parked in
`docs/plans/2026-10-21-pdf-brain-borrowings.md`.

## What

Expose Grimoire's search, extracted text, product metadata and confirmed
bestiary entries as MCP tools, served from the existing FastAPI process at
`/mcp`, so an AI assistant (Claude Code, Claude Desktop, Cursor, or anything
else that speaks MCP) can answer questions against the user's own library.

## Why

A GM preparing a session already works in an assistant. Today the only way
to get their library into that conversation is to open Grimoire, search,
copy, and paste. The in-app Session Prep assistant (`services/session_prep.py`)
goes the other way: it builds one fixed prompt from the campaign's products.
Neither lets the assistant *ask follow-up questions* of the library — "which
of my DCC adventures has a swamp hex-crawl, and what does page 14 say about
the ferryman?"

Everything needed to answer that exists already:

- `search_service.search` — two-stage semantic + keyword search with the
  best chunk and page per hit.
- `fts_service.chunk_candidates` — body-text phrase lookup with page number,
  built and deliberately *not* wired into ranking. This is its intended
  consumer.
- `processor.get_extracted_pages` / `get_extracted_text` — per-page markdown
  on disk.
- The bestiary's confirmed `monster_entries`, with the
  "pointer back into the owned book" output shape.

pdf-brain demonstrates that the useful agent surface is small: search,
multi-query search, read metadata, and *progressive disclosure* primitives
(fetch one chunk, list a document's chunks, fetch one page) so the agent
pulls a snippet first and expands only what it needs. That shape is what
this spec adopts. Its JSON envelope, "next action" hints and CLI are not
adopted; MCP tool descriptions and structured results do that job.

## Design principles

- **Read-only in v1.** No tool writes to the library. Tags, run notes and
  collections come later, behind the same review posture as the UI.
- **The library's content stays local.** The server returns the owner's own
  extracted text to the owner's own assistant. Whether that text then goes
  to a cloud model is the user's existing choice of assistant, exactly as
  it is for the in-app AI providers; the Settings privacy notice applies.
- **Reuse, don't re-implement.** Tools are thin adapters over services
  already used by the HTTP routes. No second search path, no second ranking.
- **Token budget is a feature.** Results are compact by default; full text
  is fetched one page or one window at a time. A search hit never carries
  the whole `ProductResponse`.
- **Same process, same config.** No separate daemon, no second database
  connection, no duplicated Ollama or provider settings.

## Architecture

### Transport: Streamable HTTP, mounted in FastAPI

The official `mcp` Python SDK is attached to the existing app:

```python
# grimoire/mcp/server.py
mcp_server = MCPServer("grimoire", instructions=INSTRUCTIONS)
mcp_app = mcp_server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True, ...)
# grimoire/main.py
app.add_route("/mcp", mcp_app)
```

> ⚠️ **Corrections.** The SDK is at 2.x, where `FastMCP` became `MCPServer`
> and the transport options moved onto `streamable_http_app()`. And the
> sub-app is registered with `add_route`, not `app.mount`: a Starlette mount
> at `/mcp` answers a POST to `/mcp` with a 307 to `/mcp/`, and not every MCP
> client follows redirects on POST. With `add_route` the sub-app owns the
> `/mcp` path itself.

The SDK's session manager must run for the app's lifetime; it is started
inside the existing `lifespan` in `main.py` (`async with
mcp_server.session_manager.run():`). `stateless_http=True` avoids per-session
bookkeeping; every tool call is independent.

Why HTTP and not stdio:

- **Both installs work unchanged.** Docker users already publish port 8000;
  native Windows users already run uvicorn from `start-headless.bat`. The
  endpoint is `http://localhost:8000/mcp` in both cases.
- **No host-side Python.** A stdio server would have to run on the host with
  the backend's dependencies (torch among them) or be a separate package.
- **Clients speak it.** Claude Code: `claude mcp add --transport http grimoire
  http://localhost:8000/mcp`. Cursor and others take a `url` entry. A client
  that is stdio-only can bridge with `npx mcp-remote`.

### Module layout

```
backend/grimoire/mcp/
├── __init__.py
├── server.py        # FastMCP instance, instructions, tool registration
├── tools_search.py  # search_library, find_phrase, search_pack
├── tools_products.py# get_product, list_products, get_page, get_text
├── tools_bestiary.py# list_monsters
└── tools_meta.py    # library_stats
```

Each tool module opens its own `AsyncSession` via the existing session
factory (the same way the queue worker does), because MCP handlers run
outside FastAPI's dependency injection.

### Tools (v1)

All tools return structured JSON. Errors raise so the SDK reports them as
tool errors with a message the agent can act on ("product 412 has no
extracted text; ask the user to run text extraction").

| Tool | Backed by | Returns |
|---|---|---|
| `search_library(query, limit=10, game_system?, product_type?, level_min?, level_max?)` | `search_service.search` | Ranked hits: `product_id, title, game_system, product_type, publisher, level_min, level_max, score, match_type, matched_page, snippet`, plus the query `interpretation`. |
| `find_phrase(phrase, limit=10, game_system?, product_type?)` | `fts_service.chunk_candidates` | Where the library says a thing: `product_id, title, page, snippet` (with `<mark>` stripped). This is the body-text keyword path; the description tells the agent to use it for names and exact terms, and `search_library` for topics. |
| `search_pack(queries[], limit_per_query=10, global_limit?)` | `search_library` × N | Deduped by product; each hit keeps its best score and `matched_queries`. For an agent that fans out "swamp", "marsh", "bog" in one call. |
| `get_product(product_id)` | `products.get_product` | Full metadata, tags, collections, `page_count`, `text_extracted`, `has_page_anchors`. |
| `list_products(query?, game_system?, product_type?, tag?, collection_id?, limit=25, offset=0)` | `products.list_products` | Compact rows for browsing; same filters the UI drawer exposes. |
| `get_page(product_id, page, context_pages=0)` | `processor.get_extracted_pages` | Markdown for one page, optionally with N pages either side. Legacy flat extractions (no page anchors) error with a hint to re-extract. |
| `get_text(product_id, offset=0, max_chars=8000)` | `processor.get_extracted_text` | A window of the full markdown with `total_chars` and `next_offset`. Hard cap 20 000 chars per call. |
| `list_monsters(environment?, hd_min?, hd_max?, system?, book_product_id?, limit=25)` | `monsters.list_monsters` (confirmed only) | `name, book_title, product_id, page_number, hd_dice, ac, environments` — pointers, never stat-block prose, per the bestiary spec. |
| `library_stats()` | counts + `semantic_search_status` | Product count, extracted count, embedded count, provider in use. Doubles as the health check. |

### Search without a semantic provider

`search_service.search` embeds the query unconditionally. The HTTP route
guards this by rejecting when `semantic_search_provider` is `none`. The MCP
tool must not reject: with no provider it falls back to
`fts_service.search_fts` over metadata and reports `mode: "keyword_only"`
in the result so the agent can tell the user why topical queries are weak.

### Server instructions

`FastMCP(instructions=...)` carries the workflow guidance pdf-brain puts in
its hint engine:

> Start with `search_library` for topics or `find_phrase` for names and
> exact terms. Every hit carries a `matched_page`; call `get_page` on it
> before quoting. Use `get_text` only when a page is not enough. Results
> are the user's own library; cite as *Title, p. N*.

### Middleware

`RateLimitMiddleware` is applied to the whole app, and an agent fanning out
`search_pack` plus several `get_page` calls would trip a per-IP limit tuned
for a browser.

> ⚠️ **Correction.** No exemption was needed: the middleware already skips
> every path outside `/api/`, so `/mcp` was never limited. The server test
> enables the limiter with a threshold of one request and confirms three
> MCP calls all succeed, so a future change to the middleware's scope will
> be noticed. `CacheMiddleware` is for GET responses and does not apply.

### Security posture

The API has no authentication today and the MCP mount inherits that. This
spec does not change the posture, but it widens what an unauthenticated
caller can read (full extracted text by product id, which `GET
/products/{id}/text` already allows). The SDK's DNS-rebinding host check
is switched off for the same reason: the API has no host check, and
leaving one on only for `/mcp` would reject a user who reaches Grimoire
by a LAN hostname while protecting nothing the rest of the API does not
already expose. Docker users who publish 8000 on all
interfaces are exposing the same surface they already were. A note goes in
the README's MCP section; an auth token is a follow-up, not v1.

## Out of scope for v1

- Write tools (add tag, add run note, add to collection).
- MCP resources (`grimoire://product/{id}/page/{n}`) and prompts. Tools
  cover the need; resources can be added without breaking clients.
- Extraction tools (`get_tables`, `get_statblocks`, `get_toc`). Cheap to
  add once the pattern exists; left out to keep v1 reviewable.
- Campaign and session tools. The in-app Session Prep stays as is.
- Auth token for the `/mcp` mount.

## Testing

- `tests/mcp/test_tools_*.py` — each tool function called directly against
  the test database fixture: shape of results, filters, the
  no-extracted-text error, the legacy-flat-file error, the `max_chars` cap,
  `search_pack` dedupe keeping the best score and all matched queries.
- `tests/mcp/test_server.py` — the mounted endpoint answers `initialize`
  and `tools/list` through the SDK's streamable HTTP client over an ASGI
  transport, and one `tools/call` round-trips. Confirms the lifespan wiring.
- `tests/mcp/test_keyword_fallback.py` — provider `none` returns
  `mode: "keyword_only"` instead of raising.
- Rate limiter exemption covered by a test that fires more calls than the
  browser threshold.

## Acceptance criteria

- [x] `claude mcp add --transport http grimoire http://localhost:8000/mcp`
      followed by "what adventures in my library are set in a swamp?"
      returns titles with page references, on both the Docker and the
      native Windows install.
- [x] A follow-up "what does page N of that say?" returns that page's
      markdown without the agent needing the product's file path.
- [x] `find_phrase("Kurabanda")` returns *SF1 Volturnus* with a page number.
- [x] `list_monsters(environment="swamp")` returns name, book and page only.
- [x] No tool call exceeds 20 000 characters of returned text.
- [x] With semantic search unconfigured, `search_library` still answers in
      keyword mode and says so.
- [x] All new code under `backend/grimoire/mcp/`, no file over 500 lines,
      no changes to `search_service` or `fts_service` ranking.
- [x] README gains an "Use with an AI assistant" section with the Claude
      Code one-liner and the security note.
