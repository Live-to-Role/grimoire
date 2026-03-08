"""Tests for batch queue deduplication."""

import pytest
from grimoire.models import Product, ProcessingQueue
from grimoire.services.scanner import queue_products_for_processing


@pytest.mark.asyncio
async def test_queue_products_batch_dedup(db):
    """Queuing products should use batch dedup, not per-product queries."""
    products = []
    for i in range(10):
        p = Product(
            file_path=f"/test/batch_{i}.pdf",
            file_name=f"batch_{i}.pdf",
            file_size=1000,
            file_hash=f"batchhash_{i}",
            title=f"Batch {i}",
        )
        db.add(p)
        products.append(p)
    await db.flush()

    # Pre-add a pending cover task for product 0
    existing = ProcessingQueue(
        product_id=products[0].id,
        task_type="cover",
        priority=3,
        status="pending",
    )
    db.add(existing)
    await db.flush()

    result = await queue_products_for_processing(db, products)

    # Should queue 9 covers (skipping product 0 which already has one)
    assert result["covers"] == 9


@pytest.mark.asyncio
async def test_queue_skips_duplicates(db):
    """Should not queue products marked as duplicates."""
    p = Product(
        file_path="/test/dup.pdf",
        file_name="dup.pdf",
        file_size=1000,
        file_hash="duphash",
        title="Dup",
        is_duplicate=True,
    )
    db.add(p)
    await db.flush()

    result = await queue_products_for_processing(db, [p])
    assert result["covers"] == 0
