"""Tests for concurrent queue worker with semaphore."""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_worker_respects_concurrency_limit():
    """Worker should not exceed max_concurrent_processing simultaneous tasks."""
    max_concurrent = 2
    concurrent_count = 0
    peak_concurrent = 0

    async def mock_process_item(item_id):
        nonlocal concurrent_count, peak_concurrent
        concurrent_count += 1
        peak_concurrent = max(peak_concurrent, concurrent_count)
        await asyncio.sleep(0.05)  # simulate work
        concurrent_count -= 1
        return True

    with patch(
        "grimoire.services.queue_processor.process_queue_item",
        side_effect=mock_process_item,
    ), patch(
        "grimoire.services.queue_processor.async_session_maker"
    ) as mock_session:
        mock_db = AsyncMock()
        # Mock the recovery query (stuck "processing" items) to return empty
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        items = [MagicMock(id=i, status="pending") for i in range(5)]

        call_count = 0

        async def mock_get_pending_batch(db, batch_size):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return items
            return []

        with patch(
            "grimoire.services.queue_processor.get_pending_batch",
            side_effect=mock_get_pending_batch,
        ):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            stop_event = asyncio.Event()

            async def stop_after_processing():
                await asyncio.sleep(0.5)
                stop_event.set()

            from grimoire.services.queue_processor import run_queue_worker

            asyncio.create_task(stop_after_processing())
            await run_queue_worker(
                poll_interval=0.1,
                batch_size=5,
                stop_event=stop_event,
                max_concurrent=max_concurrent,
            )

    assert peak_concurrent <= max_concurrent, (
        f"Peak concurrent tasks ({peak_concurrent}) exceeded limit ({max_concurrent})"
    )


@pytest.mark.asyncio
async def test_worker_processes_batch_concurrently():
    """Worker should run multiple tasks concurrently (not serially)."""
    task_starts = []
    task_ends = []

    async def mock_process_item(item_id):
        task_starts.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.1)
        task_ends.append(asyncio.get_event_loop().time())
        return True

    with patch(
        "grimoire.services.queue_processor.process_queue_item",
        side_effect=mock_process_item,
    ), patch(
        "grimoire.services.queue_processor.async_session_maker"
    ) as mock_session:
        mock_db = AsyncMock()
        # Mock the recovery query (stuck "processing" items) to return empty
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        items = [MagicMock(id=i, status="pending") for i in range(3)]

        call_count = 0

        async def mock_get_pending_batch(db, batch_size):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return items
            return []

        with patch(
            "grimoire.services.queue_processor.get_pending_batch",
            side_effect=mock_get_pending_batch,
        ):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            stop_event = asyncio.Event()

            async def stop_after():
                await asyncio.sleep(0.5)
                stop_event.set()

            from grimoire.services.queue_processor import run_queue_worker

            asyncio.create_task(stop_after())
            await run_queue_worker(
                poll_interval=0.1,
                batch_size=5,
                stop_event=stop_event,
                max_concurrent=3,
            )

    # If tasks ran concurrently, total time should be ~0.1s, not ~0.3s
    if task_starts and task_ends:
        total_time = max(task_ends) - min(task_starts)
        assert total_time < 0.25, (
            f"Tasks took {total_time:.2f}s — they ran serially, not concurrently"
        )
