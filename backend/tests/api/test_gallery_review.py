"""Confirming a product really is image content clears it from review.

Reviewing ~971 products is only tractable if the queue shrinks. Marking a scan
removes it from the gallery outright; confirming a pack has to remove it from
the *review* queue while leaving it exactly as it is.

The gallery route had no tests before this file, so these carry the whole
load — no existing test would catch a routing or response-shape mistake.
"""
import pytest
from httpx import ASGITransport, AsyncClient

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
async def pack(db):
    product = Product(
        file_path=r"D:\Games\Fantasy Art.pdf",
        file_name="Fantasy Art.pdf",
        file_size=50_000_000,
        file_hash="aaa",
        title="Fantasy Art Subscription",
        product_type="Stock Art",
        is_image_content=True,
        images_extracted=True,
        image_count=201,
        page_count=201,
    )
    db.add(product)
    await db.commit()
    return product


@pytest.mark.asyncio
async def test_confirming_stamps_reviewed(client, db, pack):
    response = await client.post(
        "/api/v1/gallery/confirm-images", json={"product_ids": [pack.id]}
    )

    assert response.status_code == 200
    assert response.json() == {"reviewed": 1}
    assert pack.classification_reviewed_at is not None


@pytest.mark.asyncio
async def test_confirming_changes_nothing_else(client, db, pack):
    """It is a verdict, not an edit."""
    await client.post("/api/v1/gallery/confirm-images", json={"product_ids": [pack.id]})

    assert pack.is_image_content is True
    assert pack.is_scanned is False
    assert pack.product_type == "Stock Art"
    assert pack.image_count == 201


@pytest.fixture
async def one_reviewed_one_not(db):
    from datetime import datetime, UTC

    reviewed = Product(
        file_path=r"D:\a.pdf", file_name="a.pdf", file_size=1, file_hash="a",
        title="Already Judged", is_image_content=True,
        classification_reviewed_at=datetime.now(UTC),
    )
    pending = Product(
        file_path=r"D:\b.pdf", file_name="b.pdf", file_size=1, file_hash="b",
        title="Not Yet Judged", is_image_content=True,
    )
    db.add_all([reviewed, pending])
    await db.commit()
    return reviewed, pending


@pytest.mark.asyncio
async def test_gallery_defaults_to_unreviewed_only(client, one_reviewed_one_not):
    """The backlog has to visibly shrink, so this is the default."""
    response = await client.get("/api/v1/gallery")

    titles = [i["title"] for i in response.json()["items"]]
    assert titles == ["Not Yet Judged"]


@pytest.mark.asyncio
async def test_gallery_can_show_everything(client, one_reviewed_one_not):
    response = await client.get("/api/v1/gallery", params={"needs_review": "false"})

    titles = sorted(i["title"] for i in response.json()["items"])
    assert titles == ["Already Judged", "Not Yet Judged"]


@pytest.mark.asyncio
async def test_gallery_reports_how_many_are_left(client, one_reviewed_one_not):
    response = await client.get("/api/v1/gallery", params={"needs_review": "false"})

    body = response.json()
    assert body["total"] == 2
    assert body["needs_review_total"] == 1
