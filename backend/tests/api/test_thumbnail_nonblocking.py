"""Test that thumbnail endpoint doesn't block on generation."""

import pytest
import inspect


@pytest.mark.asyncio
async def test_thumbnail_uses_background_generation():
    """Thumbnail generation should not block the response."""
    from grimoire.api.routes.products import get_product_thumbnail

    source = inspect.getsource(get_product_thumbnail)
    # Should NOT call generate_thumbnail_for_product synchronously
    # Should either use to_thread, queue to worker, or return cover fallback
    assert "to_thread" in source or "ProcessingQueue" in source, (
        "get_product_thumbnail must not call generate_thumbnail_for_product synchronously"
    )
