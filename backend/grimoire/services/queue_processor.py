"""Queue processor service - processes items from the ProcessingQueue table."""

import asyncio
import logging
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
    
    success = process_cover_sync(product)
    if success:
        await db.commit()
    return success


@register_handler("text")
async def handle_text_task(db: AsyncSession, product: Product) -> bool:
    """Handle text extraction task.
    
    If the PDF is detected as image-based (needs OCR), queues an ocr_text task instead.
    """
    from grimoire.services.processor import process_text_extraction_sync
    from grimoire.services.fts_service import update_search_vector
    from grimoire.processors.text_extractor import detect_needs_ocr
    from pathlib import Path
    
    # Check if this PDF needs OCR
    pdf_path = Path(product.file_path)
    if pdf_path.exists():
        detection = detect_needs_ocr(pdf_path)
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
    
    success = process_text_extraction_sync(product, use_marker=False)
    if success:
        await db.commit()
        # Also update the FTS index
        await update_search_vector(db, product)
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
        # Extract text using OCR
        markdown_text = extract_with_ocr(pdf_path, dpi=200, lang="eng")
        
        # Save the extracted text
        text_dir = settings.data_dir / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        
        text_file = text_dir / f"{product.id}.json"
        
        # Get page count
        import fitz
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        doc.close()
        
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
        
        product.extracted_text_path = str(text_file)
        product.text_extracted = True
        await db.commit()
        
        # Update FTS index
        await update_search_vector(db, product)
        
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
    
    text = get_extracted_text(product)
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


async def process_queue_item(item_id: int) -> bool:
    """
    Process a single queue item.
    
    Args:
        item_id: ID of the queue item to process
        
    Returns:
        True if successful, False otherwise
    """
    async with async_session_maker() as db:
        # Get the queue item
        query = select(ProcessingQueue).where(ProcessingQueue.id == item_id)
        result = await db.execute(query)
        item = result.scalar_one_or_none()
        
        if not item:
            logger.warning(f"Queue item {item_id} not found")
            return False
        
        if item.status != "pending":
            logger.debug(f"Queue item {item_id} is not pending (status: {item.status})")
            return False
        
        # Mark as processing
        item.status = "processing"
        item.started_at = datetime.now(UTC)
        item.attempts += 1
        await db.commit()
        
        # Get the product
        product_query = select(Product).where(Product.id == item.product_id)
        product_result = await db.execute(product_query)
        product = product_result.scalar_one_or_none()
        
        if not product:
            item.status = "failed"
            item.error_message = "Product not found"
            item.completed_at = datetime.now(UTC)
            await db.commit()
            return False
        
        # Get the handler
        handler = TASK_HANDLERS.get(item.task_type)
        if not handler:
            item.status = "failed"
            item.error_message = f"Unknown task type: {item.task_type}"
            item.completed_at = datetime.now(UTC)
            await db.commit()
            return False
        
        # Execute the task
        try:
            success = await handler(db, product)
            
            if success:
                item.status = "completed"
                item.completed_at = datetime.now(UTC)
                logger.info(f"Queue item {item_id} completed successfully")
            else:
                if item.attempts >= item.max_attempts:
                    item.status = "failed"
                    item.error_message = "Max attempts reached"
                else:
                    item.status = "pending"  # Retry later
                item.completed_at = datetime.now(UTC)
                logger.warning(f"Queue item {item_id} failed (attempt {item.attempts})")
            
            await db.commit()
            return success
            
        except Exception as e:
            logger.error(f"Error processing queue item {item_id}: {e}")
            item.error_message = str(e)[:500]
            
            if item.attempts >= item.max_attempts:
                item.status = "failed"
            else:
                item.status = "pending"  # Retry later
            
            item.completed_at = datetime.now(UTC)
            await db.commit()
            return False


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


async def process_queue(max_items: int = 10, delay: float = 0.5) -> dict:
    """
    Process pending items from the queue.
    
    Args:
        max_items: Maximum number of items to process
        delay: Delay between items (seconds)
        
    Returns:
        Summary of processing results
    """
    processed = 0
    succeeded = 0
    failed = 0
    
    async with async_session_maker() as db:
        for _ in range(max_items):
            item = await get_next_pending_item(db)
            
            if not item:
                break
            
            processed += 1
            success = await process_queue_item(item.id)
            
            if success:
                succeeded += 1
            else:
                failed += 1
            
            # Small delay between items
            if delay > 0:
                await asyncio.sleep(delay)
    
    return {
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
    }


async def run_queue_worker(
    poll_interval: float = 5.0,
    batch_size: int = 5,
    stop_event: asyncio.Event | None = None,
) -> None:
    """
    Run the queue worker continuously.
    
    Args:
        poll_interval: Seconds between polling for new items
        batch_size: Number of items to process per batch
        stop_event: Event to signal worker to stop
    """
    logger.info("Queue worker started")
    
    while True:
        if stop_event and stop_event.is_set():
            logger.info("Queue worker stopping")
            break
        
        try:
            result = await process_queue(max_items=batch_size, delay=0.1)
            
            if result["processed"] > 0:
                logger.info(
                    f"Processed {result['processed']} items: "
                    f"{result['succeeded']} succeeded, {result['failed']} failed"
                )
        except Exception as e:
            logger.error(f"Queue worker error: {e}")
        
        await asyncio.sleep(poll_interval)
