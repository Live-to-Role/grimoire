"""POST /queue/reclassify-pending-maps diverts blacklisted/keyword maps off the text queue."""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from grimoire.main import app
from grimoire.database import get_db
from grimoire.models.product import Product
from grimoire.models import ProcessingQueue
from grimoire.services.tag_service import seed_builtin_tags


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reclassify_pending_maps_diverts_blacklist(client, db):
    # set_content_type_tag requires the builtin "Map" tag to already exist
    # (see tests/api/test_bulk_reclassify.py's seeded_tags fixture for the
    # established pattern this mirrors).
    await seed_builtin_tags(db)

    # Blacklisted publisher -> diverted with no file open
    hmap = Product(file_path=r"D:\Drivethrurpg\Heroic Maps\HeroicMaps_Cliffs.pdf",
                   file_name="HeroicMaps_Cliffs.pdf", file_size=1, file_hash="h1")
    # Regular book -> untouched
    book = Product(file_path=r"D:\Drivethrurpg\Wizards\Players_Handbook.pdf",
                   file_name="Players_Handbook.pdf", file_size=1, file_hash="h2")
    db.add_all([hmap, book])
    await db.commit()

    db.add_all([
        ProcessingQueue(product_id=hmap.id, task_type="text", status="pending"),
        ProcessingQueue(product_id=book.id, task_type="text", status="pending"),
    ])
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/queue/reclassify-pending-maps")
    assert resp.status_code == 200
    body = resp.json()
    assert body["diverted"] == 1

    await db.refresh(hmap)
    await db.refresh(book)
    assert hmap.is_image_content is True
    assert hmap.product_type == "Map"
    assert book.is_image_content in (False, None)

    # hmap's pending text row is gone; an extract_images row exists
    hmap_rows = (await db.execute(
        select(ProcessingQueue).where(ProcessingQueue.product_id == hmap.id)
    )).scalars().all()
    types = sorted(r.task_type for r in hmap_rows)
    assert types == ["extract_images"]

    # book's text row remains pending
    book_rows = (await db.execute(
        select(ProcessingQueue).where(ProcessingQueue.product_id == book.id)
    )).scalars().all()
    assert [r.task_type for r in book_rows] == ["text"]
