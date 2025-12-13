"""Background tasks for PDF processing."""

import asyncio
from datetime import datetime
from pathlib import Path

from grimoire.worker.queue import huey


def run_async(coro):
    """Run an async function in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@huey.task()
def process_cover(product_id: int) -> bool:
    """Extract cover image from a PDF.

    Args:
        product_id: ID of the product to process

    Returns:
        True if successful, False otherwise
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    from grimoire.database import async_session_maker
    from grimoire.models import Product
    from grimoire.services.processor import process_cover_task

    async def _process():
        async with async_session_maker() as db:
            query = select(Product).where(Product.id == product_id)
            result = await db.execute(query)
            product = result.scalar_one_or_none()

            if not product:
                return False

            return await process_cover_task(db, product)

    return run_async(_process())


@huey.task()
def process_metadata(product_id: int) -> bool:
    """Extract metadata from a PDF.

    Args:
        product_id: ID of the product to process

    Returns:
        True if successful, False otherwise
    """
    from sqlalchemy import select

    from grimoire.database import async_session_maker
    from grimoire.models import Product
    from grimoire.services.processor import extract_pdf_metadata

    async def _process():
        async with async_session_maker() as db:
            query = select(Product).where(Product.id == product_id)
            result = await db.execute(query)
            product = result.scalar_one_or_none()

            if not product:
                return False

            pdf_path = Path(product.file_path)
            if not pdf_path.exists():
                return False

            metadata = extract_pdf_metadata(pdf_path)

            if metadata.get("page_count"):
                product.page_count = metadata["page_count"]

            if metadata.get("title") and not product.title:
                product.title = metadata["title"]

            product.updated_at = datetime.utcnow()
            await db.commit()

            return True

    return run_async(_process())


@huey.task()
def scan_folder_task(folder_id: int, force: bool = False) -> int:
    """Scan a folder for new PDFs.

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

            products = await scan_folder(db, folder, force=force)
            folder.last_scanned_at = datetime.utcnow()
            await db.commit()

            return len(products)

    return run_async(_scan())


from huey import crontab

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
