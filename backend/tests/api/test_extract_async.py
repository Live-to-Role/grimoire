"""Test that text extraction doesn't block the event loop."""

import pytest


@pytest.mark.asyncio
async def test_extract_should_queue_not_block():
    """Inline text extraction endpoint should use asyncio.to_thread."""
    import inspect
    from grimoire.api.routes.products import extract_product_text

    source = inspect.getsource(extract_product_text)
    # Must use either asyncio.to_thread or queue to worker
    assert "to_thread" in source or "ProcessingQueue" in source, (
        "extract_product_text must use asyncio.to_thread or queue to worker"
    )
