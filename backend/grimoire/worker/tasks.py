"""Background tasks for PDF processing."""

import asyncio
from datetime import datetime, UTC

from huey import crontab

from grimoire.worker.queue import huey


def run_async(coro):
    """Run an async function in a sync context (Huey worker threads)."""
    return asyncio.run(coro)


@huey.task()
def scan_folder_task(folder_id: int, force: bool = False) -> int:
    """Scan a folder for new PDFs and queue them for processing.

    Args:
        folder_id: ID of the folder to scan
        force: Re-scan unchanged files

    Returns:
        Number of products found/updated
    """
    from sqlalchemy import select

    from grimoire.database import async_session_maker
    from grimoire.models import WatchedFolder
    from grimoire.services.scanner import scan_folder

    async def _scan():
        async with async_session_maker() as db:
            query = select(WatchedFolder).where(WatchedFolder.id == folder_id)
            result = await db.execute(query)
            folder = result.scalar_one_or_none()

            if not folder:
                return 0

            # scan_folder now queues products in batches during the scan
            result = await scan_folder(db, folder, force=force)
            folder.last_scanned_at = datetime.now(UTC)
            await db.commit()

            # The dedicated queue worker (grimoire.worker.run) drains the queue
            # continuously; no need to trigger processing here.
            return result.get("new_count", 0)

    return run_async(_scan())


@huey.periodic_task(crontab(minute="*/30"))
def periodic_scan() -> None:
    """Periodically scan all enabled folders."""
    from sqlalchemy import select

    from grimoire.database import async_session_maker
    from grimoire.models import WatchedFolder

    async def _scan_all():
        async with async_session_maker() as db:
            query = select(WatchedFolder).where(WatchedFolder.enabled == True)
            result = await db.execute(query)
            folders = result.scalars().all()

            for folder in folders:
                scan_folder_task(folder.id)

    run_async(_scan_all())
