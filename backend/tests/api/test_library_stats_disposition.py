"""library/stats reports image_content + unextractable counts."""
import pytest
from httpx import AsyncClient, ASGITransport

from grimoire.main import app
from grimoire.database import get_db
from grimoire.models.product import Product


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stats_reports_disposition_counts(client, db):
    db.add_all([
        Product(file_path="/t/si.pdf", file_name="si.pdf", file_size=1, file_hash="si",
                is_image_content=True),
        Product(file_path="/t/su.pdf", file_name="su.pdf", file_size=1, file_hash="su",
                text_unextractable=True),
    ])
    await db.commit()

    async with client as c:
        resp = await c.get("/api/v1/library/stats")
    assert resp.status_code == 200
    proc = resp.json()["processing"]
    assert proc["image_content"] >= 1
    assert proc["unextractable"] >= 1
