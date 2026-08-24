"""`is_image_content` and `is_scanned` are different facts.

A collection of images (a map pack) and a document whose pages are images (a
scanned module) were conflated, so scanned books were routed to image
extraction and never OCR'd. `is_scanned` survives the image flag being
cleared; `classification_reviewed_at` records that a human judged the product,
which is what lets the review backlog shrink.
"""
import pytest
from sqlalchemy import select

from grimoire.models import Product


def _product(**kw):
    base = dict(
        file_path=r"D:\Games\thing.pdf",
        file_name="thing.pdf",
        file_size=1024,
        file_hash="h",
        title="A Thing",
    )
    base.update(kw)
    return Product(**base)


@pytest.mark.asyncio
async def test_is_scanned_defaults_to_false(db):
    product = _product()
    db.add(product)
    await db.commit()

    stored = (await db.execute(select(Product))).scalar_one()
    assert stored.is_scanned is False
    assert stored.classification_reviewed_at is None


@pytest.mark.asyncio
async def test_a_product_can_be_scanned_without_being_image_content(db):
    """The state a rescued scan ends in: OCR-routed, out of the gallery."""
    from datetime import datetime, UTC

    product = _product(is_image_content=False, is_scanned=True,
                       classification_reviewed_at=datetime.now(UTC))
    db.add(product)
    await db.commit()

    stored = (await db.execute(select(Product))).scalar_one()
    assert stored.is_scanned is True
    assert stored.is_image_content is False
    assert stored.classification_reviewed_at is not None
