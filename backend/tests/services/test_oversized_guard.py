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


from grimoire.models.queue import ProcessingQueue
from grimoire.services.queue_processor import get_pending_batch


@pytest.mark.asyncio
async def test_pending_batch_orders_smallest_file_first(db):
    # Three products at the same priority with distinct file sizes, inserted
    # largest-first. The drain query must return them smallest-file-first.
    sizes = [500_000, 100_000, 300_000]  # insertion order: 500k, 100k, 300k
    product_ids = []
    for i, size in enumerate(sizes):
        p = Product(
            file_path=f"/x/ord{i}.pdf",
            file_name=f"ord{i}.pdf",
            file_size=size,
            file_hash=f"ord-{i}",
        )
        db.add(p)
        await db.commit()
        product_ids.append(p.id)
        db.add(ProcessingQueue(
            product_id=p.id, task_type="text", priority=6, status="pending",
        ))
    await db.commit()

    batch = await get_pending_batch(db, batch_size=1000)

    # Filter to just the items we created; their relative order must be
    # ascending by file_size regardless of other rows in the shared test DB.
    mine = [item for item in batch if item.product_id in product_ids]
    ordered_sizes = [sizes[product_ids.index(item.product_id)] for item in mine]
    assert ordered_sizes == sorted(ordered_sizes), (
        f"expected ascending file sizes, got {ordered_sizes}"
    )
    assert ordered_sizes[0] == 100_000


@pytest.mark.asyncio
async def test_pending_batch_surfaces_orphaned_queue_rows(db):
    # SQLite FK enforcement is off and there is no ORM cascade from
    # Product -> ProcessingQueue, so deleting a product can leave its
    # pending queue rows orphaned (product_id points nowhere). Before the
    # smallest-first join was added, get_pending_batch had no join and
    # returned these rows, letting the worker mark them failed
    # ("Product not found") and self-clean. An INNER join silently
    # excludes them, so they'd linger as pending forever. Assert the
    # orphan still surfaces so it can keep self-cleaning.
    product = Product(
        file_path="/x/orphan.pdf",
        file_name="orphan.pdf",
        file_size=123_456,
        file_hash="orphan-queue-row-1",
    )
    db.add(product)
    await db.commit()
    orphan_product_id = product.id

    queue_item = ProcessingQueue(
        product_id=orphan_product_id, task_type="text", priority=6, status="pending",
    )
    db.add(queue_item)
    await db.commit()

    # Delete the product directly, leaving the queue row's product_id dangling.
    await db.delete(product)
    await db.commit()

    batch = await get_pending_batch(db, batch_size=1000)

    mine = [item for item in batch if item.product_id == orphan_product_id]
    assert len(mine) == 1, (
        f"expected orphaned queue row for product_id={orphan_product_id} "
        f"to surface in get_pending_batch, got {len(mine)} matches"
    )
