"""POST /queue/text-extraction/retry-unextractable clears flags and re-queues."""
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
async def test_retry_unextractable(client, db):
    dead = Product(file_path="/t/u.pdf", file_name="u.pdf", file_size=1, file_hash="ru",
                   text_unextractable=True, extraction_error="no text after ocr")
    ok = Product(file_path="/t/o.pdf", file_name="o.pdf", file_size=1, file_hash="ro")
    db.add_all([dead, ok])
    await db.commit()

    # A stale failed text item from the earlier attempt should be cleared, not
    # left alongside the fresh pending one.
    db.add(ProcessingQueue(product_id=dead.id, task_type="text", status="failed",
                           error_message="no text after ocr"))
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/queue/text-extraction/retry-unextractable")
    assert resp.status_code == 200
    assert resp.json()["requeued"] >= 1  # at least our dead product was requeued

    await db.refresh(dead)
    assert dead.text_unextractable is False
    assert dead.extraction_error is None

    items = await db.execute(
        select(ProcessingQueue).where(
            ProcessingQueue.product_id == dead.id, ProcessingQueue.task_type == "text"
        )
    )
    rows = list(items.scalars().all())
    assert len(rows) == 1                 # stale failed item removed
    assert rows[0].status == "pending"    # replaced by a fresh pending retry
