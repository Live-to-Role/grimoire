"""Dedicated background queue-worker process.

Runs the ProcessingQueue drain loop OUTSIDE the API/uvicorn process so heavy CPU
work (OCR, layout extraction, embeddings) never blocks HTTP handling. This is the
single owner of ProcessingQueue draining.

Launched from start.bat / start.sh as `python -m grimoire.worker.run`.
"""
import asyncio
import signal

from grimoire.database import init_db
from grimoire.logging_config import setup_logging
from grimoire.services.queue_processor import run_queue_worker, set_processing_paused


async def main() -> None:
    setup_logging()
    await init_db()

    # Start paused every launch ("Grimoire Paused"). The worker only starts when
    # the app starts, so forcing the flag here means the app always opens paused;
    # the user enables background processing when ready.
    await set_processing_paused(True)

    stop_event = asyncio.Event()

    # POSIX: stop cleanly on SIGINT/SIGTERM. Not available on Windows'
    # ProactorEventLoop — there we rely on KeyboardInterrupt below, and the
    # worker's startup "reset stuck processing -> pending" recovers abrupt kills.
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    await run_queue_worker(poll_interval=2.0, batch_size=10, stop_event=stop_event)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
