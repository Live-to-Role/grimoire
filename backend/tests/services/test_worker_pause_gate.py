"""The worker must not process items while paused."""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_worker_skips_processing_while_paused():
    with patch(
        "grimoire.services.queue_processor.is_processing_paused",
        new=AsyncMock(return_value=True),
    ), patch(
        "grimoire.services.queue_processor.process_queue_item",
        new=AsyncMock(return_value=True),
    ) as mock_proc, patch(
        "grimoire.services.queue_processor.get_pending_batch",
        new=AsyncMock(return_value=[]),
    ) as mock_batch, patch(
        "grimoire.services.queue_processor.async_session_maker"
    ) as mock_session:
        # Mock the startup stuck-item recovery query to return no rows.
        mock_db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        stop_event = asyncio.Event()

        async def stop_soon():
            await asyncio.sleep(1.3)
            stop_event.set()

        from grimoire.services.queue_processor import run_queue_worker

        asyncio.create_task(stop_soon())
        await run_queue_worker(poll_interval=0.05, batch_size=5, stop_event=stop_event)

        mock_proc.assert_not_called()
        mock_batch.assert_not_called()
