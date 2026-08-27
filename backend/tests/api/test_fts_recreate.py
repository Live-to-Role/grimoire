"""POST /queue/fts/recreate must leave the index in a working state.

It was the obvious-looking repair endpoint and it quietly broke two things:
it built the table with a six-column schema that omitted `description`, and it
dropped all three sync triggers without ever recreating them. Anyone reaching
for it to fix a search problem would have made it permanent.

The schema and triggers belong to `_ensure_fts_table`; this endpoint should
defer to it rather than keeping a second copy that drifts.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from grimoire.database import get_db
from grimoire.main import app
from grimoire.models import Product


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def product(db):
    p = Product(
        file_path=r"D:\Games\sf1.pdf",
        file_name="sf1.pdf",
        file_size=1024,
        file_hash="sf1hash",
        title="SF1 Volturnus Planet of Mystery",
        publisher="TSR",
        text_extracted=True,
        deep_indexed=True,
    )
    db.add(p)
    await db.commit()
    return p


async def _columns(db) -> list[str]:
    rows = (await db.execute(text("PRAGMA table_info(products_fts)"))).all()
    return [r[1] for r in rows]


async def _triggers(db) -> set[str]:
    rows = (await db.execute(text(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'products_fts%'"
    ))).all()
    return {r[0] for r in rows}


async def test_recreate_keeps_the_canonical_schema(client, db, product):
    """A six-column table drops `description` and corrupts every later write."""
    async with client as c:
        resp = await c.post("/api/v1/queue/fts/recreate")

    assert resp.status_code == 200
    assert resp.json()["success"] is True, resp.json()
    # Six columns, not seven: the body moved to product_chunks_fts. What this
    # test protects is that recreate produces whatever _ensure_fts_table says
    # is canonical, rather than a second copy of the schema that can drift.
    assert await _columns(db) == [
        "title", "file_name", "publisher", "game_system",
        "product_type", "description",
    ]


async def test_recreate_restores_the_sync_triggers(client, db, product):
    """Dropping the triggers without recreating them silently stops all syncing."""
    async with client as c:
        await c.post("/api/v1/queue/fts/recreate")

    assert await _triggers(db) == {
        "products_fts_insert", "products_fts_update", "products_fts_delete",
    }

    # And the restored trigger actually works.
    product.publisher = "Judges Guild"
    await db.commit()
    rows = (await db.execute(text(
        "SELECT rowid FROM products_fts WHERE products_fts MATCH 'Judges'"
    ))).all()
    assert [r[0] for r in rows] == [product.id]


async def test_recreate_marks_products_for_reindexing(client, db, product):
    """The body lives on disk, so the rebuilt table needs a re-index pass."""
    async with client as c:
        await c.post("/api/v1/queue/fts/recreate")

    deep = (await db.execute(text(
        "SELECT deep_indexed FROM products WHERE id = :i"), {"i": product.id}
    )).scalar_one()
    assert deep == 0
