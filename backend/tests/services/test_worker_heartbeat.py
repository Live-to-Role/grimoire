"""The queue worker publishes a heartbeat so diagnostics can tell it is alive.

"Nothing is processing" has two very different causes — the worker is paused,
or the worker process is not running at all. Only a heartbeat separates them.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from grimoire.models import Setting
from grimoire.services.queue_processor import (
    WORKER_HEARTBEAT_KEY,
    get_worker_heartbeat,
    touch_worker_heartbeat,
)


def _maker(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def test_heartbeat_absent_when_worker_never_ran(engine):
    heartbeat = await get_worker_heartbeat(session_maker=_maker(engine))
    assert heartbeat is None


async def test_touch_writes_a_utc_timestamp(engine):
    maker = _maker(engine)
    before = datetime.now(UTC)
    await touch_worker_heartbeat(session_maker=maker)

    heartbeat = await get_worker_heartbeat(session_maker=maker)
    assert heartbeat is not None
    assert heartbeat.tzinfo is not None
    assert before - timedelta(seconds=5) <= heartbeat <= datetime.now(UTC) + timedelta(seconds=5)


async def test_touch_updates_the_existing_row(engine):
    maker = _maker(engine)
    await touch_worker_heartbeat(session_maker=maker)
    await touch_worker_heartbeat(session_maker=maker)

    async with maker() as session:
        rows = await session.execute(select(Setting).where(Setting.key == WORKER_HEARTBEAT_KEY))
        assert len(rows.scalars().all()) == 1


async def test_corrupt_heartbeat_reads_as_missing(engine):
    maker = _maker(engine)
    async with maker() as session:
        result = await session.execute(select(Setting).where(Setting.key == WORKER_HEARTBEAT_KEY))
        setting = result.scalar_one_or_none()
        if setting is None:
            session.add(Setting(key=WORKER_HEARTBEAT_KEY, value="not-a-timestamp"))
        else:
            setting.value = "not-a-timestamp"
        await session.commit()

    assert await get_worker_heartbeat(session_maker=maker) is None


async def test_worker_loop_beats_while_paused():
    """A paused worker is still a running worker, and must keep beating."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    with patch(
        "grimoire.services.queue_processor.is_processing_paused",
        new=AsyncMock(return_value=True),
    ), patch(
        "grimoire.services.queue_processor.touch_worker_heartbeat",
        new=AsyncMock(),
    ) as mock_beat, patch(
        "grimoire.services.queue_processor.async_session_maker"
    ) as mock_session:
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

        assert mock_beat.await_count >= 2
