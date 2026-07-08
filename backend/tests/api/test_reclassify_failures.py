"""POST /queue/reclassify-failures flags permanent no-text failures, keeps transient."""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from grimoire.main import app
from grimoire.database import get_db
from grimoire.models.product import Product
from grimoire.models import ProcessingQueue


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reclassify_flags_permanent_keeps_transient(client, db):
    perm = Product(file_path="/t/p.pdf", file_name="p.pdf", file_size=1, file_hash="rp")
    trans = Product(file_path="/t/t.pdf", file_name="t.pdf", file_size=1, file_hash="rt")
    img = Product(file_path="/t/g.pdf", file_name="g.pdf", file_size=1, file_hash="rg",
                  is_image_content=True)
    db.add_all([perm, trans, img])
    await db.commit()

    db.add_all([
        ProcessingQueue(product_id=perm.id, task_type="ocr_text", status="failed",
                        error_message="no text after ocr"),
        ProcessingQueue(product_id=trans.id, task_type="text", status="failed",
                        error_message="tesseract not installed"),
        ProcessingQueue(product_id=img.id, task_type="text", status="failed",
                        error_message="whatever"),
    ])
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/queue/reclassify-failures")
    assert resp.status_code == 200
    body = resp.json()
    assert body["flagged"] >= 1
    assert body["cleared"] >= 2      # perm + img failed items removed
    assert body["left_retryable"] >= 1

    await db.refresh(perm)
    await db.refresh(trans)
    assert perm.text_unextractable is True

    # transient failed item remains
    remaining = await db.execute(
        select(ProcessingQueue).where(ProcessingQueue.product_id == trans.id)
    )
    assert len(list(remaining.scalars().all())) == 1

    # second run is a no-op (idempotent) — create a fresh client
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c2:
        resp2 = await c2.post("/api/v1/queue/reclassify-failures")
    assert resp2.json()["cleared"] == 0
