"""Background tasks for PDF processing."""

import asyncio
from datetime import datetime, UTC
from pathlib import Path

from huey import crontab

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

            product.updated_at = datetime.now(UTC)
            await db.commit()

            return True

    return run_async(_process())


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
            
            # Trigger queue processing to handle any queued items
            process_queue_task()

            return result.get("new_count", 0)

    return run_async(_scan())


@huey.task()
def process_queue_task(batch_size: int = 50) -> int:
    """Process pending items from the ProcessingQueue.
    
    Uses the registered task handlers from queue_processor to handle
    all task types (text, ocr_text, embed, fts_index, cover, identify).
    
    Args:
        batch_size: Number of items to process per run
        
    Returns:
        Number of items processed
    """
    from sqlalchemy import select
    
    from grimoire.database import async_session_maker
    from grimoire.models import ProcessingQueue
    from grimoire.services.queue_processor import process_queue_item
    
    async def _process():
        async with async_session_maker() as db:
            # Get pending items ordered by priority
            query = (
                select(ProcessingQueue)
                .where(ProcessingQueue.status == "pending")
                .order_by(ProcessingQueue.priority.desc(), ProcessingQueue.created_at.asc())
                .limit(batch_size)
            )
            result = await db.execute(query)
            items = list(result.scalars().all())
            
            if not items:
                return 0
            
            processed = 0
            for item in items:
                # Use the queue processor which has all task handlers
                success = await process_queue_item(item.id)
                if success:
                    processed += 1
            
            # If there are more pending items, queue another batch
            remaining = await db.execute(
                select(ProcessingQueue).where(ProcessingQueue.status == "pending").limit(1)
            )
            if remaining.scalar_one_or_none():
                process_queue_task()  # Queue next batch
                
            return processed
    
    return run_async(_process())


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
