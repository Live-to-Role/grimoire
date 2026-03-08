"""Tests for batch queue insertion during scanning."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_queue_products_uses_batch_insert():
    """Queue insertion should batch products instead of one-by-one INSERT+SELECT."""
    from grimoire.services.scanner import queue_products_for_processing

    products = []
    for i in range(100):
        p = MagicMock()
        p.id = i + 1
        p.is_duplicate = False
        p.cover_extracted = False
        p.text_extracted = False
        p.ai_identified = False
        products.append(p)

    db = AsyncMock()

    # Mock settings to enable text extraction
    with patch(
        "grimoire.services.scanner.get_scan_settings",
        new_callable=AsyncMock,
        return_value={"auto_extract_text_on_scan": True, "auto_identify_on_scan": False},
    ):
        # Mock the existing queue check to return no existing items
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        result = await queue_products_for_processing(db, products)

    # Should have queued covers and text for all 100 products
    assert result["covers"] == 100
    assert result["text"] == 100

    # Key assertion: db.commit should be called a small number of times (batched),
    # not 200 times (once per item per task type)
    assert db.commit.call_count <= 3, (
        f"Expected batched commits but got {db.commit.call_count} commits"
    )
