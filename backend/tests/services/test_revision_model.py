import pytest
from sqlalchemy import select
from grimoire.models.product import Product
from grimoire.database import _backfill_normalized_stems


@pytest.mark.asyncio
async def test_product_has_superseded_fields(db):
    """Product model has is_superseded, superseded_by_id, normalized_stem."""
    product = Product(
        file_path="/test/book.pdf",
        file_name="book.pdf",
        title="Book",
        file_hash="abc123",
        file_size=12345,
        normalized_stem="book",
    )
    db.add(product)
    await db.flush()

    result = await db.execute(select(Product).where(Product.id == product.id))
    p = result.scalar_one()
    assert p.normalized_stem == "book"
    assert p.is_superseded is False
    assert p.superseded_by_id is None


@pytest.mark.asyncio
async def test_superseded_by_relationship(db):
    """superseded_by relationship resolves to the newer product."""
    old = Product(file_path="/test/old.pdf", file_name="old.pdf", title="Old", file_hash="aaa", file_size=100)
    new = Product(file_path="/test/new.pdf", file_name="new.pdf", title="New", file_hash="bbb", file_size=200)
    db.add_all([old, new])
    await db.flush()

    old.is_superseded = True
    old.superseded_by_id = new.id
    await db.flush()

    result = await db.execute(select(Product).where(Product.id == old.id))
    p = result.scalar_one()
    assert p.superseded_by_id == new.id
    assert p.is_superseded is True


@pytest.mark.asyncio
async def test_backfill_normalized_stems(db):
    """Backfill computes normalized_stem for products missing it."""
    p1 = Product(
        file_path="/test/Monster_Manual-PDF.pdf",
        file_name="Monster_Manual-PDF.pdf",
        title="Monster Manual",
        file_hash="aaa",
        file_size=12345,
    )
    p2 = Product(
        file_path="/test/Monster_Manual-PDF_(Revised).pdf",
        file_name="Monster_Manual-PDF_(Revised).pdf",
        title="Monster Manual Revised",
        file_hash="bbb",
        file_size=12345,
        normalized_stem="already_set",
    )
    db.add_all([p1, p2])
    await db.commit()

    await _backfill_normalized_stems(db)

    result = await db.execute(select(Product).where(Product.id == p1.id))
    assert result.scalar_one().normalized_stem == "monster_manual"

    # Should not overwrite existing stem
    result = await db.execute(select(Product).where(Product.id == p2.id))
    assert result.scalar_one().normalized_stem == "already_set"
