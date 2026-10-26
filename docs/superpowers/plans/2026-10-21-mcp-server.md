# MCP Server — Implementation Plan

**Date:** 2026-10-21
**Spec:** `docs/superpowers/specs/2026-10-21-mcp-server-design.md`
**Status:** Executed 2026-10-21 in one pass except the final live assistant check, done 2026-10-25 after merge; kept as the record of the steps and what each one found.

## Steps

- [x] **Confirm the SDK.** `pip install mcp` in a scratch venv; inspect the
      2.x API (`MCPServer`, `streamable_http_app`, `Client` for in-process
      tests, `ToolError` at `mcp.server.mcpserver.exceptions`). Found: the
      SDK depends on `httpx2`, which coexists with the backend's `httpx`.
- [x] **Red.** `tests/mcp/`: a disk-backed library fixture (page-anchored
      extractions, a legacy flat one, an unextracted product, a duplicate, a
      tag, a collection, two bestiary entries) and tests per tool module plus
      the server. 30 tests, all failing on import.
- [x] **Green.** `grimoire/mcp/`: `db.py` (session factory the tests can
      swap), `common.py` (compact product row, lookups, search mode),
      `tools_search.py`, `tools_products.py`, `tools_bestiary.py`,
      `tools_meta.py`, `server.py` (registration, instructions, ASGI app).
      Largest file 214 lines.
- [x] **Wire.** `main.py`: run the session manager inside the lifespan,
      `add_route("/mcp", mcp_app)`. `mcp>=2.3,<3` in `requirements.txt` and
      `pyproject.toml`.
- [x] **Mount check.** A Starlette mount at `/mcp` 307-redirects a POST to
      `/mcp/`; switched to `add_route` with the sub-app owning `/mcp`.
- [x] **Rate limiter.** Already skips non-`/api/` paths; the server test
      pins that with the limiter forced on at one request per window.
- [x] **Lint and suite.** `ruff check` clean on new code; full backend
      suite in the light venv.
- [x] **Docs.** README section; spec corrections marked inline; borrowings
      backlog for the parked items.
- [x] **Live check, protocol.** Backend started from the Docker image with
      the new code mounted: `initialize`, `tools/list` (all nine), a
      `tools/call`, and a tool error all answered on `/mcp`; `/mcp/`
      redirects to `/mcp`; with the limiter forced to one request per
      minute `/api/v1/health` returned 429 on its second call while `/mcp`
      kept answering.
- [x] **Live check, assistant.** On the real library: `claude mcp add
      --transport http grimoire http://localhost:8000/mcp`, then ask for
      swamp adventures and a page from one of them. Done 2026-10-25 after
      merge: eight tool calls, six swamp adventures each summarised from its
      matched page via `get_page`, cited as *Title, p. N*. Two title-only
      hits came back without a `matched_page` and the assistant correctly
      declined to quote them; the server instructions now say what to do
      with such a hit instead of promising every hit has a page.

## Running the tests without Docker

The backend's tests do not need torch. A venv with the non-ML dependencies
runs the whole suite in seconds:

```bash
python3 -m venv .venv-lite
.venv-lite/bin/pip install "fastapi>=0.109" uvicorn "sqlalchemy[asyncio]>=2.0.25" aiosqlite \
  "pydantic>=2.5" pydantic-settings python-multipart aiofiles numpy httpx huey redis \
  watchfiles pymupdf pdfplumber pillow pytest pytest-asyncio "mcp>=2.3,<3"
cd backend && PYTHONPATH=. DATA_DIR=/tmp/gdata COVERS_DIR=/tmp/gdata/covers \
  ../.venv-lite/bin/python -m pytest -p no:cacheprovider -q
```
