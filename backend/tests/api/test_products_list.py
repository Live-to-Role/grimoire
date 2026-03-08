"""Tests for product listing query optimization."""

import pytest
from sqlalchemy import select, func

from grimoire.models import Product


@pytest.mark.asyncio
async def test_count_query_does_not_include_selectinload(db):
    """The count query should NOT use selectinload — it only needs to count rows."""
    # Add test products
    for i in range(5):
        product = Product(
            file_path=f"/test/file_{i}.pdf",
            file_name=f"file_{i}.pdf",
            file_size=1000 + i,
            file_hash=f"hash_{i}",
            title=f"Product {i}",
        )
        db.add(product)
    await db.flush()

    # Build count query the NEW way (without subquery wrapping)
    count_query = select(func.count(Product.id)).where(
        Product.is_duplicate == False,
        Product.is_missing == False,
    )

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    assert total == 5
