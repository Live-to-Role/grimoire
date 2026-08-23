"""Tests for batch queue insertion during scanning."""

from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _eligible_product(product_id: int) -> SimpleNamespace:
    """A product that should be queued for both a cover and a text extraction.

    Deliberately not a MagicMock: every flag the scanner reads is an
    auto-created truthy attribute on a MagicMock, so as the scanner grew
    `is_superseded` / `is_image_content` / `text_unextractable` filters, the
    mocks silently became ineligible and the test asserted on an empty result.
    """
    return SimpleNamespace(
        id=product_id,
        is_duplicate=False,
        is_superseded=False,
        cover_extracted=False,
        text_extracted=False,
        ai_identified=False,
        is_image_content=False,
        text_unextractable=False,
    )


@pytest.mark.asyncio
async def test_queue_products_uses_batch_insert():
    """Queue insertion should batch products instead of one-by-one INSERT+SELECT."""
    from grimoire.services.scanner import queue_products_for_processing

    products = [_eligible_product(i + 1) for i in range(100)]

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
