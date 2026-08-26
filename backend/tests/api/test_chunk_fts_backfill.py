"""Backfilling the body index, and sweeping rows their chunks left behind."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from grimoire.database import get_db
from grimoire.main import app
from grimoire.models import Product, ProductEmbedding
from grimoire.services.fts_service import (
    index_product_chunks,
    prune_orphaned_chunk_index,
)


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def indexed_product(db):
    product = Product(
        file_path=r"D:\Games\sf1.pdf",
        file_name="sf1.pdf",
        file_size=1024,
        file_hash="sf1hash",
        title="SF1 Volturnus",
        text_extracted=True,
    )
    db.add(product)
    await db.flush()
    emb = ProductEmbedding(
        product_id=product.id,
        chunk_index=0,
        chunk_text="The Kurabanda live in the treetops.",
        embedding_model="test",
        embedding_dim=3,
        page_start=32,
        page_end=33,
    )
    emb.set_embedding_vector([0.1, 0.2, 0.3])
    db.add(emb)
    await db.commit()
    return product


async def _rows(db) -> int:
    return (await db.execute(
        text("SELECT count(*) FROM product_chunks_fts")
    )).scalar_one()


async def test_prune_removes_rows_whose_chunk_is_gone(db, indexed_product):
    """Deleting a product drops its embeddings by ORM cascade; the virtual
    table has no relationship to ride, so the sweep is what cleans it up."""
    await index_product_chunks(db, indexed_product.id)
    await db.commit()
    assert await _rows(db) == 1

    await db.delete(indexed_product)
    await db.commit()

    assert await prune_orphaned_chunk_index(db) == 1
    assert await _rows(db) == 0


async def test_prune_keeps_live_rows(db, indexed_product):
    await index_product_chunks(db, indexed_product.id)
    await db.commit()

    assert await prune_orphaned_chunk_index(db) == 0
    assert await _rows(db) == 1


async def test_rebuild_chunks_queues_products_with_chunks(client, db, indexed_product):
    async with client as c:
        resp = await c.post("/api/v1/queue/fts/rebuild-chunks")

    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 1
    assert body["total"] == 1


async def test_rebuild_chunks_skips_products_already_queued(client, db, indexed_product):
    async with client as c:
        await c.post("/api/v1/queue/fts/rebuild-chunks")
        resp = await c.post("/api/v1/queue/fts/rebuild-chunks")

    assert resp.json()["skipped"] == 1
