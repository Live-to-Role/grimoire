"""reset-image-classification clears the enum's image type, not only free text.

After the reclassification, products hold the Codex enum (`map`), not the old
free-text "Map". The reset must still recognise a map, or a wrongly flagged
document keeps its image type after being reset.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from grimoire.database import get_db
from grimoire.main import app
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
async def test_reset_clears_enum_map_and_keeps_document_types(client, db):
    mapped = Product(file_path="/t/m.pdf", file_name="m.pdf", file_size=1, file_hash="m1",
                     is_image_content=True, product_type="map")
    legacy = Product(file_path="/t/l.pdf", file_name="l.pdf", file_size=1, file_hash="l1",
                     is_image_content=True, product_type="Map")
    document = Product(file_path="/t/a.pdf", file_name="a.pdf", file_size=1, file_hash="a1",
                       is_image_content=True, product_type="adventure")
    db.add_all([mapped, legacy, document])
    await db.commit()

    response = await client.post("/api/v1/library/maintenance/reset-image-classification")

    assert response.status_code == 200
    for p in (mapped, legacy, document):
        await db.refresh(p)
    assert mapped.product_type is None and legacy.product_type is None
    assert document.product_type == "adventure"
