"""Dismissing a failed item "as art" writes the enum `map`, not "Art/Maps"."""
import pytest
from httpx import ASGITransport, AsyncClient

from grimoire.database import get_db
from grimoire.main import app
from grimoire.models import ProcessingQueue, Product


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dismiss_all_failed_as_art_writes_enum_map(client, db):
    empty = Product(file_path="/t/a.pdf", file_name="a.pdf", file_size=1, file_hash="a1")
    typed = Product(file_path="/t/b.pdf", file_name="b.pdf", file_size=1, file_hash="b1",
                    product_type="adventure")
    db.add_all([empty, typed])
    await db.flush()
    db.add_all([ProcessingQueue(product_id=p.id, task_type="text", status="failed")
                for p in (empty, typed)])
    await db.commit()

    response = await client.post("/api/v1/queue/dismiss-all-failed?mark_as_art=true")

    assert response.status_code == 200
    await db.refresh(empty)
    await db.refresh(typed)
    assert empty.product_type == "map" and typed.product_type == "adventure"
