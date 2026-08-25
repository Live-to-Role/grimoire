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


@pytest.fixture
async def flagged_book(db, tmp_path):
    """The third population verification found: 1,555 of the 1,711 blocked
    products already carry real text. Un-flagging one must not re-OCR it."""
    import json

    text_file = tmp_path / "text.json"
    text_file.write_text(json.dumps({"char_count": 499_032}), encoding="utf-8")
    product = Product(
        file_path=r"D:\Games\City State.pdf",
        file_name="City State.pdf",
        file_size=50_000_000,
        file_hash="citystate",
        title="City State of the Invincible Overlord",
        product_type="Setting",
        is_image_content=True,
        page_count=216,
        text_extracted=True,
        extracted_text_path=str(text_file),
    )
    db.add(product)
    await db.commit()
    return product


@pytest.mark.asyncio
async def test_a_book_that_already_has_text_is_not_re_ocred(client, db, flagged_book):
    await client.post(
        "/api/v1/bulk/update",
        json={"product_ids": [flagged_book.id], "is_image_content": False},
    )

    queued = (await db.execute(
        select(ProcessingQueue).where(ProcessingQueue.product_id == flagged_book.id)
    )).scalars().all()
    assert queued == []
    assert flagged_book.is_scanned is False, "it has a text layer; it is not a scan"


@pytest.mark.asyncio
async def test_it_is_still_un_flagged_and_marked_reviewed(client, db, flagged_book):
    """Skipping OCR must not mean skipping the actual un-flagging."""
    await client.post(
        "/api/v1/bulk/update",
        json={"product_ids": [flagged_book.id], "is_image_content": False},
    )

    assert flagged_book.is_image_content is False
    assert flagged_book.classification_reviewed_at is not None
