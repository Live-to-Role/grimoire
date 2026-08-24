"""Un-flagging an image-content product must actually get you the text.

`bulk.py`'s un-flag branch clears the flag, nulls product_type, deletes the
extracted images from disk and removes content-type tags — but never queued
text extraction. So the one action a user has for "this is really a document"
lost the images without gaining the text.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from grimoire.database import get_db
from grimoire.main import app
from grimoire.models import ProcessingQueue, Product


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def flagged(db):
    product = Product(
        file_path=r"D:\Games\SF1 Volturnus.pdf",
        file_name="SF1 Volturnus.pdf",
        file_size=7_000_000,
        file_hash="f46e13f8",
        title="SF1 Volturnus Planet of Mystery",
        product_type="Map",
        is_image_content=True,
        images_extracted=True,
        image_count=36,
        page_count=36,
    )
    db.add(product)
    await db.commit()
    return product


@pytest.mark.asyncio
async def test_unflagging_queues_ocr(client, db, flagged):
    response = await client.post(
        "/api/v1/bulk/update",
        json={"product_ids": [flagged.id], "is_image_content": False},
    )

    assert response.status_code == 200
    queued = (await db.execute(
        select(ProcessingQueue).where(ProcessingQueue.product_id == flagged.id)
    )).scalars().all()
    assert [q.task_type for q in queued] == ["ocr_text"]


@pytest.mark.asyncio
async def test_unflagging_marks_it_scanned_and_reviewed(client, db, flagged):
    await client.post(
        "/api/v1/bulk/update",
        json={"product_ids": [flagged.id], "is_image_content": False},
    )

    assert flagged.is_scanned is True
    assert flagged.classification_reviewed_at is not None
    assert flagged.is_image_content is False


@pytest.mark.asyncio
async def test_unflagging_still_clears_the_existing_fields(client, db, flagged):
    """Destructive semantics are unchanged — one code path with the Library."""
    await client.post(
        "/api/v1/bulk/update",
        json={"product_ids": [flagged.id], "is_image_content": False},
    )

    assert flagged.product_type is None
    assert flagged.images_extracted is False
    assert flagged.image_count is None


@pytest.mark.asyncio
async def test_a_rescued_scan_becomes_codex_eligible(client, db, flagged):
    """Phase 3 made image-content products ineligible to contribute. A scan
    misclassified as image content inherited that, so rescuing it has to give
    the eligibility back — otherwise the fix leaves a second wrong answer."""
    from grimoire.services.codex_eligibility import is_codex_eligible

    assert is_codex_eligible(flagged)[0] is False

    await client.post(
        "/api/v1/bulk/update",
        json={"product_ids": [flagged.id], "is_image_content": False},
    )

    assert is_codex_eligible(flagged) == (True, "eligible")
