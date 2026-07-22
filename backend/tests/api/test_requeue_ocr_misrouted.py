"""POST /queue/text-extraction/requeue-ocr-misrouted re-queues misrouted OCR books."""
import json
import shutil

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


def _write_extraction(tmp_path, name, method):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({"method": method, "markdown": "x"}), encoding="utf-8")
    return str(path)


def _own_copy(tmp_path, source, name):
    """Product.file_path is UNIQUE — every product needs its own PDF."""
    path = tmp_path / f"{name}.pdf"
    shutil.copyfile(source, path)
    return str(path)


@pytest.mark.asyncio
async def test_requeues_only_ocr_products_with_a_text_layer(
    client, db, tmp_path, text_pdf, scanned_pdf, monkeypatch
):
    from grimoire.processors import text_extractor

    good_path = _own_copy(tmp_path, text_pdf, "good")
    scan_path = _own_copy(tmp_path, scanned_pdf, "scan")
    fine_path = _own_copy(tmp_path, text_pdf, "fine")

    misrouted = Product(
        file_path=good_path, file_name="good.pdf", file_size=1, file_hash="rm1",
        text_extracted=True,
        extracted_text_path=_write_extraction(tmp_path, "misrouted", "tesseract_ocr"),
    )
    true_scan = Product(
        file_path=scan_path, file_name="scan.pdf", file_size=1, file_hash="rm2",
        text_extracted=True,
        extracted_text_path=_write_extraction(tmp_path, "scan", "tesseract_ocr"),
    )
    already_fine = Product(
        file_path=fine_path, file_name="fine.pdf", file_size=1, file_hash="rm3",
        text_extracted=True,
        extracted_text_path=_write_extraction(tmp_path, "fine", "pymupdf4llm"),
    )
    db.add_all([misrouted, true_scan, already_fine])
    await db.commit()

    # Force deterministic verdicts regardless of the fixtures' exact char counts.
    verdicts = {good_path: False, scan_path: True, fine_path: False}
    monkeypatch.setattr(
        text_extractor,
        "assess_text_layer",
        lambda path, *a, **k: {"needs_ocr": verdicts[str(path)], "reason": "test"},
    )

    async with client as c:
        resp = await c.post(
            "/api/v1/queue/text-extraction/requeue-ocr-misrouted",
            params={"limit": 500, "after_id": misrouted.id - 1},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ocr_products"] == 2
    assert body["requeued"] == 1
    assert body["still_ocr"] == 1
    assert body["last_id"] == already_fine.id

    queued = await db.execute(
        select(ProcessingQueue).where(ProcessingQueue.task_type == "text")
    )
    product_ids = {item.product_id for item in queued.scalars().all()}
    assert misrouted.id in product_ids
    assert true_scan.id not in product_ids
    assert already_fine.id not in product_ids


@pytest.mark.asyncio
async def test_cursor_limits_the_batch(client, db, tmp_path, text_pdf, monkeypatch):
    from grimoire.processors import text_extractor

    monkeypatch.setattr(
        text_extractor, "assess_text_layer",
        lambda path, *a, **k: {"needs_ocr": False, "reason": "test"},
    )
    first = Product(
        file_path=_own_copy(tmp_path, text_pdf, "a"),
        file_name="a.pdf", file_size=1, file_hash="rc1",
        text_extracted=True,
        extracted_text_path=_write_extraction(tmp_path, "a", "tesseract_ocr"),
    )
    second = Product(
        file_path=_own_copy(tmp_path, text_pdf, "b"),
        file_name="b.pdf", file_size=1, file_hash="rc2",
        text_extracted=True,
        extracted_text_path=_write_extraction(tmp_path, "b", "tesseract_ocr"),
    )
    db.add_all([first, second])
    await db.commit()

    async with client as c:
        resp = await c.post(
            "/api/v1/queue/text-extraction/requeue-ocr-misrouted",
            params={"limit": 1, "after_id": first.id - 1},
        )

    body = resp.json()
    assert body["scanned"] == 1
    assert body["last_id"] == first.id
    assert body["done"] is False
