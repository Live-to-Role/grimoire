"""Oversized-PDF guard: pure skip-reason helper + handler flagging + ordering."""
from types import SimpleNamespace

import pytest

from grimoire.services.queue_processor import (
    MAX_EXTRACTION_FILE_MB,
    MAX_EXTRACTION_PAGES,
    _oversized_skip_reason,
)


def test_size_over_limit_returns_reason():
    # 300 MB > 250 MB limit
    p = SimpleNamespace(file_size=300 * 1024 * 1024, page_count=None)
    reason = _oversized_skip_reason(p)
    assert reason is not None
    assert "oversized" in reason
    assert "300 MB" in reason


def test_pages_over_limit_returns_reason_when_page_count_set():
    # Under size limit, but page_count exceeds MAX_EXTRACTION_PAGES
    p = SimpleNamespace(file_size=1 * 1024 * 1024, page_count=MAX_EXTRACTION_PAGES + 1)
    reason = _oversized_skip_reason(p)
    assert reason is not None
    assert "oversized" in reason
    assert str(MAX_EXTRACTION_PAGES + 1) in reason


def test_high_page_count_ignored_when_page_count_none():
    # page_count None means we never opened the file; size alone must decide
    p = SimpleNamespace(file_size=1 * 1024 * 1024, page_count=None)
    assert _oversized_skip_reason(p) is None


def test_both_under_limit_returns_none():
    p = SimpleNamespace(file_size=10 * 1024 * 1024, page_count=200)
    assert _oversized_skip_reason(p) is None


def test_missing_file_size_returns_none():
    # Defensive: file_size None should not raise, and is under limit
    p = SimpleNamespace(file_size=None, page_count=None)
    assert _oversized_skip_reason(p) is None


def test_constants_have_expected_values():
    assert MAX_EXTRACTION_FILE_MB == 250
    assert MAX_EXTRACTION_PAGES == 1000


from grimoire.models.product import Product
from grimoire.services.queue_processor import (
    TaskError,
    handle_ocr_text_task,
    handle_text_task,
)


@pytest.mark.asyncio
async def test_text_handler_flags_and_raises_on_oversized(db):
    # 300 MB > 250 MB. file_path points nowhere; the guard must fire before
    # any file access, so no real PDF is needed.
    product = Product(
        file_path="/nonexistent/huge.pdf",
        file_name="huge.pdf",
        file_size=300 * 1024 * 1024,
        file_hash="ovg-text-1",
    )
    db.add(product)
    await db.commit()

    with pytest.raises(TaskError):
        await handle_text_task(db, product)

    await db.refresh(product)
    assert product.text_unextractable is True
    assert "oversized" in (product.extraction_error or "")


@pytest.mark.asyncio
async def test_ocr_handler_flags_and_raises_on_oversized(db):
    product = Product(
        file_path="/nonexistent/huge2.pdf",
        file_name="huge2.pdf",
        file_size=300 * 1024 * 1024,
        file_hash="ovg-ocr-1",
    )
    db.add(product)
    await db.commit()

    with pytest.raises(TaskError):
        await handle_ocr_text_task(db, product)

    await db.refresh(product)
    assert product.text_unextractable is True
    assert "oversized" in (product.extraction_error or "")


@pytest.mark.asyncio
async def test_text_handler_does_not_flag_normal_size(db, tmp_path):
    # A small, missing-on-disk file is transient (returns False), not flagged.
    product = Product(
        file_path=str(tmp_path / "small.pdf"),
        file_name="small.pdf",
        file_size=1 * 1024 * 1024,
        file_hash="ovg-text-ok",
    )
    db.add(product)
    await db.commit()

    result = await handle_text_task(db, product)

    assert result is False
    await db.refresh(product)
    assert not product.text_unextractable
