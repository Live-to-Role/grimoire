"""Tests for queue processor thread offloading."""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_cover_task_runs_in_thread():
    """Cover extraction must not block the event loop."""
    from grimoire.services.queue_processor import handle_cover_task

    product = MagicMock()
    product.id = 1
    db = AsyncMock()

    with patch(
        "grimoire.services.processor.process_cover_sync", return_value=True
    ) as mock_sync, patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = True
        await handle_cover_task(db, product)
        mock_thread.assert_called_once_with(mock_sync, product)


@pytest.mark.asyncio
async def test_text_task_runs_in_thread():
    """Text extraction must not block the event loop."""
    from grimoire.services.queue_processor import handle_text_task

    product = MagicMock()
    product.id = 1
    product.file_path = "/fake/path.pdf"
    db = AsyncMock()

    to_thread_calls = []

    async def tracking_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func.__name__ if hasattr(func, '__name__') else str(func))
        if func.__name__ == "detect_needs_ocr":
            return {"needs_ocr": False}
        return True

    with patch(
        "asyncio.to_thread", side_effect=tracking_to_thread
    ), patch(
        "grimoire.services.fts_service.update_search_vector",
        new_callable=AsyncMock,
    ), patch(
        "grimoire.services.queue_processor.queue_ai_identify_if_enabled",
        new_callable=AsyncMock,
    ), patch("pathlib.Path.exists", return_value=True):
        await handle_text_task(db, product)
        # to_thread should be called for both detect_needs_ocr and process_text_extraction_sync
        assert "detect_needs_ocr" in to_thread_calls
        assert "process_text_extraction_sync" in to_thread_calls


@pytest.mark.asyncio
async def test_event_loop_not_blocked_during_sync_task():
    """Verify that the event loop remains responsive while a sync task runs."""
    import time

    async def check_loop_responsive():
        """This coroutine should complete promptly if the loop isn't blocked."""
        start = asyncio.get_event_loop().time()
        await asyncio.sleep(0)  # yield to event loop
        elapsed = asyncio.get_event_loop().time() - start
        return elapsed < 0.1  # should be near-instant

    def slow_sync_work():
        time.sleep(0.2)
        return True

    # Run slow work in thread - loop should stay responsive
    task = asyncio.create_task(asyncio.to_thread(slow_sync_work))
    responsive = await check_loop_responsive()
    await task

    assert responsive, "Event loop was blocked during sync work"
