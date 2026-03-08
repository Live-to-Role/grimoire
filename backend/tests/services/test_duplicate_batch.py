"""Tests for batch duplicate detection."""

import pytest
from grimoire.models import Product
from grimoire.services.duplicate_service import batch_check_and_mark_duplicates


@pytest.mark.asyncio
async def test_batch_duplicate_detection(db):
    """Batch duplicate check should mark duplicates in one pass."""
    # Create a canonical product
    canonical = Product(
        file_path="/test/original.pdf",
        file_name="original.pdf",
        file_size=1000,
        file_hash="shared_hash",
        title="Original",
    )
    db.add(canonical)
    await db.flush()

    # Create products with the same hash
    dupes = []
    for i in range(3):
        p = Product(
            file_path=f"/test/dupe_{i}.pdf",
            file_name=f"dupe_{i}.pdf",
            file_size=1000,
            file_hash="shared_hash",
            title=f"Dupe {i}",
        )
        db.add(p)
        dupes.append(p)
    await db.flush()

    count = await batch_check_and_mark_duplicates(db, dupes)
    assert count == 3
    for p in dupes:
        assert p.is_duplicate is True
        assert p.duplicate_of_id == canonical.id


@pytest.mark.asyncio
async def test_batch_no_duplicates(db):
    """Products with unique hashes should not be marked."""
    products = []
    for i in range(3):
        p = Product(
            file_path=f"/test/unique_{i}.pdf",
            file_name=f"unique_{i}.pdf",
            file_size=1000,
            file_hash=f"unique_hash_{i}",
            title=f"Unique {i}",
        )
        db.add(p)
        products.append(p)
    await db.flush()

    count = await batch_check_and_mark_duplicates(db, products)
    assert count == 0
