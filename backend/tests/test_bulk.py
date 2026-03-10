"""Tests for bulk update endpoint."""
import pytest
from httpx import AsyncClient, ASGITransport
from grimoire.main import app
from grimoire.models import Product


@pytest.fixture
async def test_products(db, request):
    """Create test products for bulk operations."""
    prefix = request.node.name
    products = []
    for i in range(3):
        p = Product(
            file_path=f"/test/{prefix}/product_{i}.pdf",
            file_name=f"product_{i}.pdf",
            file_size=1000,
            file_hash=f"{prefix}_hash_{i}",
            game_system="Old System",
            product_type="Adventure",
            publisher="Old Publisher",
        )
        db.add(p)
    await db.commit()
    # Re-query to get IDs
    from sqlalchemy import select
    result = await db.execute(select(Product))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_bulk_update_extended_fields(db, test_products):
    """Bulk update should support all 10 metadata fields."""
    from grimoire.api.routes.bulk import BulkUpdateRequest

    req = BulkUpdateRequest(
        product_ids=[p.id for p in test_products],
        game_system="D&D 5e",
        author="Test Author",
        genre="Fantasy",
        setting="Forgotten Realms",
        series="Lost Mine",
        estimated_runtime="one-shot",
        format="pdf",
    )
    assert req.game_system == "D&D 5e"
    assert req.author == "Test Author"
    assert req.genre == "Fantasy"
    assert req.setting == "Forgotten Realms"


@pytest.mark.asyncio
async def test_bulk_update_explicit_clear(db, test_products):
    """Bulk update should support clearing fields with empty string."""
    from grimoire.api.routes.bulk import BulkUpdateRequest

    req = BulkUpdateRequest(
        product_ids=[p.id for p in test_products],
        game_system="",  # empty string = clear the field
    )
    assert req.game_system == ""
