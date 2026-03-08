"""Queue processor service - processes items from the ProcessingQueue table."""

import asyncio
import logging
import time
from datetime import datetime, UTC
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.database import async_session_maker
from grimoire.models import ProcessingQueue, Product

logger = logging.getLogger(__name__)

# Task type handlers
TASK_HANDLERS = {}


def register_handler(task_type: str):
    """Decorator to register a task handler."""
    def decorator(func):
        TASK_HANDLERS[task_type] = func
        return func
    return decorator


@register_handler("cover")
async def handle_cover_task(db: AsyncSession, product: Product) -> bool:
    """Handle cover extraction task."""
    from grimoire.services.processor import process_cover_sync

    success = await asyncio.to_thread(process_cover_sync, product)
    if success:
        await db.commit()
    return success


# Simple TTL cache for settings (avoids DB query per task)
_settings_cache: dict[str, tuple[float, any]] = {}
_SETTINGS_CACHE_TTL = 60.0  # seconds


async def get_setting(db: AsyncSession, key: str, default=None):
    """Get a setting value from the database, with 60-second TTL cache."""
    from grimoire.models import Setting
    import json

    now = time.monotonic()
    if key in _settings_cache:
        cached_time, cached_value = _settings_cache[key]
        if now - cached_time < _SETTINGS_CACHE_TTL:
            return cached_value

    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        try:
            value = json.loads(setting.value)
        except (json.JSONDecodeError, TypeError):
            value = setting.value
    else:
        value = default

    _settings_cache[key] = (now, value)
    return value


async def queue_ai_identify_if_enabled(db: AsyncSession, product: Product) -> bool:
    """Queue AI identification task if auto-identify is enabled and a provider is available."""
    auto_identify = await get_setting(db, "auto_identify_on_scan", False)
    if not auto_identify:
        return False

    # Check if already identified
    if product.ai_identified:
        return False

    # Check if any AI provider is actually available before queuing
    from grimoire.processors.ai_identifier import get_setting_from_db, check_ollama_available
    import os

    provider = await get_setting(db, "auto_identify_provider", "ollama")
    if provider == "openai":
        key = os.getenv("OPENAI_API_KEY", "") or await get_setting_from_db("openai_api_key")
        if not key:
            return False
    elif provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "") or await get_setting_from_db("anthropic_api_key")
        if not key:
            return False
    elif provider == "ollama":
        if not check_ollama_available():
            return False

    # Queue AI identify task
    ai_item = ProcessingQueue(
        product_id=product.id,
        task_type="ai_identify",
        priority=3,  # Lower than text extraction
        status="pending",
    )
    db.add(ai_item)
    logger.info(f"Queued AI identification for product {product.id}")
    return True


@register_handler("text")
async def handle_text_task(db: AsyncSession, product: Product) -> bool:
    """Handle text extraction task.
    
    If the PDF is detected as image-based (needs OCR), queues an ocr_text task instead.
    After successful extraction, queues AI identification if enabled.
    """
    from grimoire.services.processor import process_text_extraction_sync
    from grimoire.services.fts_service import update_search_vector
    from grimoire.processors.text_extractor import detect_needs_ocr
    from pathlib import Path
    
    # Check if this PDF needs OCR
    pdf_path = Path(product.file_path)
    if pdf_path.exists():
        # detect_needs_ocr opens PDF with fitz — run in thread
        detection = await asyncio.to_thread(detect_needs_ocr, pdf_path)
        if detection["needs_ocr"]:
            # Queue OCR task instead
            ocr_item = ProcessingQueue(
                product_id=product.id,
                task_type="ocr_text",
                priority=1,  # Lower priority - OCR is slow
                status="pending",
            )
            db.add(ocr_item)
            await db.commit()
            logger.info(f"Product {product.id} needs OCR: {detection['reason']}")
            return True  # Successfully queued OCR task

    # Run sync extraction in thread pool
    success = await asyncio.to_thread(process_text_extraction_sync, product, False)
    if success:
        await db.commit()
        # Also update the FTS index
        await update_search_vector(db, product)
        # Queue AI identification if enabled
        await queue_ai_identify_if_enabled(db, product)
        await db.commit()
    return success


@register_handler("ocr_text")
async def handle_ocr_text_task(db: AsyncSession, product: Product) -> bool:
    """Handle OCR text extraction task for image-based PDFs.
    
    This is a separate queue for slow OCR processing.
    """
    from grimoire.services.fts_service import update_search_vector
    from grimoire.processors.text_extractor import extract_with_ocr, TESSERACT_AVAILABLE
    from grimoire.config import settings
    from pathlib import Path
    import json
    
    if not TESSERACT_AVAILABLE:
        logger.error("OCR task failed: pytesseract/pdf2image not available")
        return False
    
    pdf_path = Path(product.file_path)
    if not pdf_path.exists():
        return False
    
    try:
        # OCR is extremely CPU-heavy — must run in thread
        markdown_text = await asyncio.to_thread(
            extract_with_ocr, pdf_path, 200, "eng"
        )

        # File I/O in thread too
        def _save_ocr_result():
            import fitz
            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)
            doc.close()

            text_dir = settings.data_dir / "text"
            text_dir.mkdir(parents=True, exist_ok=True)
            text_file = text_dir / f"{product.id}.json"

            result = {
                "markdown": markdown_text,
                "total_pages": total_pages,
                "pages_extracted": f"1-{total_pages}",
                "method": "tesseract_ocr",
                "char_count": len(markdown_text),
                "ocr_used": True,
            }

            with open(text_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            return str(text_file), total_pages

        text_file_path, _ = await asyncio.to_thread(_save_ocr_result)

        product.extracted_text_path = text_file_path
        product.text_extracted = True
        await db.commit()
        
        # Update FTS index
        await update_search_vector(db, product)
        
        # Queue AI identification if enabled
        await queue_ai_identify_if_enabled(db, product)
        await db.commit()
        
        logger.info(f"OCR extraction completed for product {product.id}: {len(markdown_text)} chars")
        return True
        
    except Exception as e:
        logger.error(f"OCR extraction failed for product {product.id}: {e}")
        return False


class TaskError(Exception):
    """Exception for task failures with specific error messages."""
    pass


@register_handler("fts_index")
async def handle_fts_index_task(db: AsyncSession, product: Product) -> bool:
    """Handle FTS indexing task for products with extracted text."""
    from grimoire.services.fts_service import update_search_vector, check_fts_available
    
    # Check if FTS5 table exists
    if not await check_fts_available(db):
        raise TaskError("FTS5 table 'products_fts' does not exist. Run database migrations.")
    
    if not product.text_extracted:
        raise TaskError(f"Product {product.id} has no extracted text (text_extracted=False)")
    
    success = await update_search_vector(db, product)
    if not success:
        raise TaskError(f"FTS indexing failed for product {product.id}")
    return True


@register_handler("embed")
async def handle_embed_task(db: AsyncSession, product: Product) -> bool:
    """Handle embedding generation task for semantic search."""
    from grimoire.services.processor import get_extracted_text
    from grimoire.services.embeddings import generate_embeddings, chunk_text
    from grimoire.models import ProductEmbedding
    from sqlalchemy import delete
    
    if not product.text_extracted:
        return False
    
    # get_extracted_text reads JSON from disk — run in thread
    text = await asyncio.to_thread(get_extracted_text, product)
    if not text:
        return False

    try:
        # Delete existing embeddings
        await db.execute(
            delete(ProductEmbedding).where(ProductEmbedding.product_id == product.id)
        )
        
        # Chunk and embed
        chunks = chunk_text(text, 500, 50)
        embeddings = await generate_embeddings(chunks)
        
        for i, (chunk, emb_result) in enumerate(zip(chunks, embeddings)):
            embedding_record = ProductEmbedding(
                product_id=product.id,
                chunk_index=i,
                chunk_text=chunk[:1000],
                embedding_model=emb_result.model,
                embedding_dim=len(emb_result.embedding),
            )
            embedding_record.set_embedding_vector(emb_result.embedding)
            db.add(embedding_record)
        
        await db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to generate embeddings for product {product.id}: {e}")
        return False


@register_handler("identify")
async def handle_identify_task(db: AsyncSession, product: Product) -> bool:
    """Handle AI identification task."""
    from grimoire.services.codex import get_codex_client
    
    client = get_codex_client()
    
    # Try hash lookup first
    match = await client.identify_by_hash(product.file_hash)
    
    if not match or not match.product:
        # Fall back to title lookup
        match = await client.identify_by_title(
            title=product.title or product.file_name,
            filename=product.file_name,
        )
    
    if match and match.product:
        codex_product = match.product
        
        # Update product with Codex data
        if codex_product.title and not product.title:
            product.title = codex_product.title
        if codex_product.publisher and not product.publisher:
            product.publisher = codex_product.publisher
        if codex_product.game_system and not product.game_system:
            product.game_system = codex_product.game_system
        if codex_product.product_type and not product.product_type:
            product.product_type = codex_product.product_type
        if codex_product.publication_year and not product.publication_year:
            product.publication_year = codex_product.publication_year
        
        product.ai_identified = True
        product.identification_confidence = match.confidence
        product.updated_at = datetime.now(UTC)
        await db.commit()
        return True
    
    return False


@register_handler("ai_identify")
async def handle_ai_identify_task(db: AsyncSession, product: Product) -> bool:
    """Handle AI identification task using configured provider."""
    from grimoire.processors.ai_identifier import identify_product
    from grimoire.services.processor import get_extracted_text

    # Get configured provider
    provider = await get_setting(db, "auto_identify_provider", "ollama")

    # Get extracted text — file I/O, run in thread
    text = await asyncio.to_thread(get_extracted_text, product)
    if not text or len(text) < 100:
        raise TaskError(f"Insufficient text for AI identification ({len(text) if text else 0} chars)")

    # Call AI identifier
    identification = await identify_product(text, provider=provider)

    if "error" in identification:
        raise TaskError(f"AI identify ({provider}): {identification['error']}")

    # Apply identification results
    if identification.get("game_system"):
        product.game_system = identification["game_system"]
    if identification.get("genre"):
        product.genre = identification["genre"]
    if identification.get("product_type"):
        product.product_type = identification["product_type"]
    if identification.get("publisher"):
        product.publisher = identification["publisher"]
    if identification.get("author"):
        product.author = identification["author"]
    if identification.get("title"):
        product.title = identification["title"]
    if identification.get("publication_year"):
        product.publication_year = identification["publication_year"]
    if identification.get("level_range_min"):
        product.level_range_min = identification["level_range_min"]
    if identification.get("level_range_max"):
        product.level_range_max = identification["level_range_max"]

    product.ai_identified = True
    product.updated_at = datetime.now(UTC)
    await db.commit()

    logger.info(f"AI identified product {product.id} using {provider}")
    return True


async def _process_item_with_session(db: AsyncSession, item: ProcessingQueue) -> bool:
    """Process a queue item using an existing session.

    Args:
        db: Active database session
        item: The queue item to process (already loaded)

    Returns:
        True if successful, False otherwise
    """
    if item.status != "pending":
        logger.debug(f"Queue item {item.id} is not pending (status: {item.status})")
        return False

    # Mark as processing
    item.status = "processing"
    item.started_at = datetime.now(UTC)
    item.attempts += 1
    await db.commit()

    # Get the product
    product_result = await db.execute(
        select(Product).where(Product.id == item.product_id)
    )
    product = product_result.scalar_one_or_none()

    if not product:
        item.status = "failed"
        item.error_message = "Product not found"
        item.completed_at = datetime.now(UTC)
        await db.commit()
        return False

    handler = TASK_HANDLERS.get(item.task_type)
    if not handler:
        item.status = "failed"
        item.error_message = f"Unknown task type: {item.task_type}"
        item.completed_at = datetime.now(UTC)
        await db.commit()
        return False

    try:
        success = await handler(db, product)

        if success:
            item.status = "completed"
            logger.info(f"Queue item {item.id} completed successfully")
        elif item.attempts >= item.max_attempts:
            item.status = "failed"
            item.error_message = "Max attempts reached"
        else:
            item.status = "pending"
        item.completed_at = datetime.now(UTC)

        await db.commit()

        # Emit SSE event
        from grimoire.services.event_bus import event_bus
        if success:
            await event_bus.publish("queue", {
                "type": "task_completed",
                "id": item.id,
                "task_type": item.task_type,
                "product_id": item.product_id,
            })
        elif item.status == "failed":
            await event_bus.publish("queue", {
                "type": "task_failed",
                "id": item.id,
                "task_type": item.task_type,
                "product_id": item.product_id,
                "error": item.error_message,
            })

        return success

    except Exception as e:
        logger.error(f"Error processing queue item {item.id}: {e}")
        item.error_message = str(e)[:500]
        item.status = "failed" if item.attempts >= item.max_attempts else "pending"
        item.completed_at = datetime.now(UTC)
        await db.commit()

        from grimoire.services.event_bus import event_bus
        await event_bus.publish("queue", {
            "type": "task_failed",
            "id": item.id,
            "task_type": item.task_type,
            "product_id": item.product_id,
            "error": str(e)[:200],
        })

        return False


async def process_queue_item(item_id: int) -> bool:
    """Process a single queue item by ID (for external API callers).

    Args:
        item_id: ID of the queue item to process

    Returns:
        True if successful, False otherwise
    """
    async with async_session_maker() as db:
        query = select(ProcessingQueue).where(ProcessingQueue.id == item_id)
        result = await db.execute(query)
        item = result.scalar_one_or_none()

        if not item:
            logger.warning(f"Queue item {item_id} not found")
            return False

        return await _process_item_with_session(db, item)


async def get_next_pending_item(db: AsyncSession, task_type: str | None = None) -> ProcessingQueue | None:
    """
    Get the next pending item from the queue.
    
    Priority order:
    1. By created_at (oldest first - FIFO within queue)
    2. By file_size as tiebreaker (largest first for same timestamp)
    """
    query = (
        select(ProcessingQueue)
        .join(Product, ProcessingQueue.product_id == Product.id)
        .where(ProcessingQueue.status == "pending")
    )
    
    if task_type:
        query = query.where(ProcessingQueue.task_type == task_type)
    
    query = query.order_by(
        ProcessingQueue.priority.desc(),
        ProcessingQueue.created_at.asc(),
        Product.file_size.desc()  # Largest files first as tiebreaker
    ).limit(1)
    
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_pending_batch(db: AsyncSession, batch_size: int) -> list[ProcessingQueue]:
    """
    Get a batch of pending items from the queue, ordered by priority.

    Returns up to batch_size items. Priority order:
    1. Highest priority number first
    2. Oldest created_at first (FIFO within same priority)
    """
    query = (
        select(ProcessingQueue)
        .where(ProcessingQueue.status == "pending")
        .order_by(
            ProcessingQueue.priority.desc(),
            ProcessingQueue.created_at.asc(),
        )
        .limit(batch_size)
    )

    result = await db.execute(query)
    return list(result.scalars().all())


async def run_queue_worker(
    poll_interval: float = 2.0,
    batch_size: int = 10,
    stop_event: asyncio.Event | None = None,
    max_concurrent: int | None = None,
) -> None:
    """
    Run the queue worker continuously with concurrent task processing.

    Fetches a batch of pending items each cycle and processes them concurrently,
    limited by a semaphore to prevent resource exhaustion.

    Args:
        poll_interval: Seconds between polling when queue is empty
        batch_size: Max items to fetch per poll cycle
        stop_event: Event to signal worker to stop
        max_concurrent: Max simultaneous tasks (defaults to config value)
    """
    from grimoire.config import settings

    if max_concurrent is None:
        max_concurrent = settings.max_concurrent_processing

    semaphore = asyncio.Semaphore(max_concurrent)
    logger.info(
        f"Queue worker started (max_concurrent={max_concurrent}, "
        f"batch_size={batch_size}, poll_interval={poll_interval}s)"
    )

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Queue worker stopping")
            break

        try:
            async with async_session_maker() as db:
                items = await get_pending_batch(db, batch_size)

            if not items:
                await asyncio.sleep(poll_interval)
                continue

            # Process batch concurrently with semaphore
            async def _process_with_semaphore(item_id: int):
                async with semaphore:
                    return await process_queue_item(item_id)

            tasks = [
                asyncio.create_task(_process_with_semaphore(item.id))
                for item in items
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            succeeded = sum(1 for r in results if r is True)
            failed = sum(1 for r in results if r is False or isinstance(r, Exception))

            for r in results:
                if isinstance(r, Exception):
                    logger.error(f"Queue task raised exception: {r}")

            logger.info(
                f"Batch complete: {succeeded} succeeded, {failed} failed "
                f"out of {len(items)}"
            )

            from grimoire.services.event_bus import event_bus
            await event_bus.publish("queue", {
                "type": "batch_complete",
                "succeeded": succeeded,
                "failed": failed,
                "total": len(items),
            })

            # If we got a full batch, immediately poll again (more items likely)
            if len(items) >= batch_size:
                continue

        except Exception as e:
            logger.error(f"Queue worker error: {e}")

        await asyncio.sleep(poll_interval)
