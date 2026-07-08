"""queue-all (default + force) must skip image-only / unextractable products."""
import pytest
from httpx import AsyncClient, ASGITransport

from grimoire.main import app
from grimoire.database import get_db
from grimoire.models.product import Product
from grimoire.models import ProcessingQueue
from sqlalchemy import select


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


async def _count_text_items(db, product_id):
    res = await db.execute(
        select(ProcessingQueue).where(
            ProcessingQueue.product_id == product_id,
            ProcessingQueue.task_type == "text",
        )
    )
    return len(list(res.scalars().all()))


@pytest.mark.asyncio
async def test_queue_all_skips_flagged(client, db):
    normal = Product(file_path="/t/n.pdf", file_name="n.pdf", file_size=1, file_hash="n")
    image = Product(file_path="/t/i.pdf", file_name="i.pdf", file_size=1, file_hash="i",
                    is_image_content=True)
    dead = Product(file_path="/t/d.pdf", file_name="d.pdf", file_size=1, file_hash="d",
                   text_unextractable=True)
    db.add_all([normal, image, dead])
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/queue/text-extraction/queue-all")
    assert resp.status_code == 200

    assert await _count_text_items(db, normal.id) == 1
    assert await _count_text_items(db, image.id) == 0
    assert await _count_text_items(db, dead.id) == 0


@pytest.mark.asyncio
async def test_queue_all_force_also_skips_flagged(client, db):
    normal = Product(file_path="/t/n2.pdf", file_name="n2.pdf", file_size=1, file_hash="n2",
                     text_extracted=True)
    image = Product(file_path="/t/i2.pdf", file_name="i2.pdf", file_size=1, file_hash="i2",
                    is_image_content=True)
    db.add_all([normal, image])
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/queue/text-extraction/queue-all", params={"force": True})
    assert resp.status_code == 200

    assert await _count_text_items(db, normal.id) == 1   # force re-does extracted
    assert await _count_text_items(db, image.id) == 0     # but still skips image-only
