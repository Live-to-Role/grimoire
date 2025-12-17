"""Processing queue API endpoints."""

from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func

from grimoire.api.deps import DbSession
from grimoire.models import ProcessingQueue, Product


router = APIRouter()


class QueueStats(BaseModel):
    """Queue statistics."""
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    total: int = 0


class QueueItemResponse(BaseModel):
    """Response for a queue item."""
    id: int
    product_id: int
    product_name: str | None = None
    task_type: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    error_message: str | None = None
    estimated_cost: float | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CreateQueueItemRequest(BaseModel):
    """Request to create a queue item."""
    product_id: int
    task_type: str = Field(..., description="Type: extract, identify, suggest_tags")
    priority: int = Field(5, ge=1, le=10)
    estimated_cost: float | None = None


@router.get("/stats")
async def get_queue_stats(db: DbSession) -> QueueStats:
    """Get queue statistics."""
    query = select(
        ProcessingQueue.status,
        func.count(ProcessingQueue.id).label("count")
    ).group_by(ProcessingQueue.status)
    
    result = await db.execute(query)
    rows = result.all()
    
    stats = QueueStats()
    for status, count in rows:
        if status == "pending":
            stats.pending = count
        elif status == "processing":
            stats.processing = count
        elif status == "completed":
            stats.completed = count
        elif status == "failed":
            stats.failed = count
        stats.total += count
    
    return stats


@router.get("")
async def list_queue_items(
    db: DbSession,
    status: str | None = Query(None, description="Filter by status"),
    task_type: str | None = Query(None, description="Filter by task type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """List queue items with optional filters."""
    query = select(ProcessingQueue).order_by(
        ProcessingQueue.priority.desc(),
        ProcessingQueue.created_at.asc()
    )
    
    if status:
        query = query.where(ProcessingQueue.status == status)
    if task_type:
        query = query.where(ProcessingQueue.task_type == task_type)
    
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    items = list(result.scalars().all())
    
    # Get product names
    product_ids = [item.product_id for item in items]
    if product_ids:
        products_query = select(Product).where(Product.id.in_(product_ids))
        products_result = await db.execute(products_query)
        products = {p.id: p for p in products_result.scalars().all()}
    else:
        products = {}
    
    return {
        "items": [
            QueueItemResponse(
                id=item.id,
                product_id=item.product_id,
                product_name=products.get(item.product_id, Product()).file_name,
                task_type=item.task_type,
                status=item.status,
                priority=item.priority,
                attempts=item.attempts,
                max_attempts=item.max_attempts,
                error_message=item.error_message,
                estimated_cost=item.estimated_cost,
                created_at=item.created_at,
                started_at=item.started_at,
                completed_at=item.completed_at,
            )
            for item in items
        ],
        "total": len(items),
    }


@router.post("")
async def create_queue_item(
    db: DbSession,
    request: CreateQueueItemRequest,
) -> QueueItemResponse:
    """Add an item to the processing queue."""
    # Verify product exists
    product_query = select(Product).where(Product.id == request.product_id)
    product_result = await db.execute(product_query)
    product = product_result.scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Check for duplicate pending task
    existing_query = select(ProcessingQueue).where(
        ProcessingQueue.product_id == request.product_id,
        ProcessingQueue.task_type == request.task_type,
        ProcessingQueue.status.in_(["pending", "processing"])
    )
    existing_result = await db.execute(existing_query)
    existing = existing_result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Task already queued for this product"
        )
    
    item = ProcessingQueue(
        product_id=request.product_id,
        task_type=request.task_type,
        priority=request.priority,
        estimated_cost=request.estimated_cost,
        status="pending",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    
    return QueueItemResponse(
        id=item.id,
        product_id=item.product_id,
        product_name=product.file_name,
        task_type=item.task_type,
        status=item.status,
        priority=item.priority,
        attempts=item.attempts,
        max_attempts=item.max_attempts,
        error_message=item.error_message,
        estimated_cost=item.estimated_cost,
        created_at=item.created_at,
        started_at=item.started_at,
        completed_at=item.completed_at,
    )


@router.post("/batch")
async def create_batch_queue(
    db: DbSession,
    product_ids: list[int],
    task_type: str = Query(..., description="Task type for all items"),
    priority: int = Query(5, ge=1, le=10),
) -> dict:
    """Add multiple items to the queue."""
    # Verify products exist
    products_query = select(Product).where(Product.id.in_(product_ids))
    products_result = await db.execute(products_query)
    products = {p.id: p for p in products_result.scalars().all()}
    
    created = 0
    skipped = 0
    
    for product_id in product_ids:
        if product_id not in products:
            skipped += 1
            continue
        
        # Check for existing
        existing_query = select(ProcessingQueue).where(
            ProcessingQueue.product_id == product_id,
            ProcessingQueue.task_type == task_type,
            ProcessingQueue.status.in_(["pending", "processing"])
        )
        existing_result = await db.execute(existing_query)
        if existing_result.scalar_one_or_none():
            skipped += 1
            continue
        
        item = ProcessingQueue(
            product_id=product_id,
            task_type=task_type,
            priority=priority,
            status="pending",
        )
        db.add(item)
        created += 1
    
    await db.commit()
    
    return {
        "created": created,
        "skipped": skipped,
        "total": len(product_ids),
    }


@router.post("/text-extraction/queue-all")
async def queue_all_for_text_extraction(
    db: DbSession,
    force: bool = Query(False, description="Re-queue already extracted products"),
) -> dict:
    """Queue all products that need text extraction."""
    # Find products without text extraction
    if force:
        query = select(Product).order_by(Product.file_size.desc())
    else:
        query = select(Product).where(
            Product.text_extracted == False
        ).order_by(Product.file_size.desc())
    
    result = await db.execute(query)
    products = list(result.scalars().all())
    
    created = 0
    skipped = 0
    
    for product in products:
        # Check for existing pending/processing task
        existing_query = select(ProcessingQueue).where(
            ProcessingQueue.product_id == product.id,
            ProcessingQueue.task_type == "text",
            ProcessingQueue.status.in_(["pending", "processing"])
        )
        existing_result = await db.execute(existing_query)
        if existing_result.scalar_one_or_none():
            skipped += 1
            continue
        
        item = ProcessingQueue(
            product_id=product.id,
            task_type="text",
            priority=5,
            status="pending",
        )
        db.add(item)
        created += 1
    
    await db.commit()
    
    return {
        "message": f"Queued {created} products for text extraction",
        "created": created,
        "skipped": skipped,
        "total": len(products),
    }


@router.post("/fts/rebuild-all")
async def rebuild_fts_index(
    db: DbSession,
    batch_size: int = Query(100, ge=1, le=1000, description="Batch size"),
) -> dict:
    """Queue all products with extracted text for FTS indexing."""
    # Find products with text extracted but not deep indexed
    query = select(Product).where(
        Product.text_extracted == True,
        Product.deep_indexed == False,
    ).order_by(Product.file_size.desc())
    
    result = await db.execute(query)
    products = list(result.scalars().all())
    
    created = 0
    skipped = 0
    
    for product in products:
        # Check for existing pending/processing task
        existing_query = select(ProcessingQueue).where(
            ProcessingQueue.product_id == product.id,
            ProcessingQueue.task_type == "fts_index",
            ProcessingQueue.status.in_(["pending", "processing"])
        )
        existing_result = await db.execute(existing_query)
        if existing_result.scalar_one_or_none():
            skipped += 1
            continue
        
        item = ProcessingQueue(
            product_id=product.id,
            task_type="fts_index",
            priority=8,  # Lower priority than other tasks
            status="pending",
        )
        db.add(item)
        created += 1
    
    await db.commit()
    
    return {
        "message": f"Queued {created} products for FTS indexing",
        "created": created,
        "skipped": skipped,
        "total": len(products),
    }


@router.get("/fts/stats")
async def get_fts_stats(db: DbSession) -> dict:
    """Get FTS indexing statistics and diagnose issues."""
    from sqlalchemy import text
    
    # Check if FTS5 table exists
    fts_exists = False
    fts_schema = None
    fts_count = 0
    
    try:
        result = await db.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='products_fts'")
        )
        fts_exists = result.fetchone() is not None
        
        if fts_exists:
            # Get table schema
            schema_result = await db.execute(text("PRAGMA table_info(products_fts)"))
            columns = [row[1] for row in schema_result.fetchall()]
            fts_schema = columns
            
            # Count indexed items
            count_result = await db.execute(text("SELECT COUNT(*) FROM products_fts"))
            fts_count = count_result.scalar() or 0
    except Exception as e:
        fts_schema = f"Error: {e}"
    
    # Products with text but not indexed
    need_indexing_query = select(func.count()).select_from(Product).where(
        Product.text_extracted == True,
        Product.deep_indexed == False,
    )
    need_result = await db.execute(need_indexing_query)
    need_indexing = need_result.scalar() or 0
    
    # Products fully indexed
    indexed_query = select(func.count()).select_from(Product).where(
        Product.deep_indexed == True,
    )
    indexed_result = await db.execute(indexed_query)
    indexed = indexed_result.scalar() or 0
    
    # Check for schema issue
    has_extracted_text_column = fts_schema and "extracted_text" in fts_schema if isinstance(fts_schema, list) else False
    
    return {
        "fts_table_exists": fts_exists,
        "fts_schema": fts_schema,
        "fts_indexed_count": fts_count,
        "has_extracted_text_column": has_extracted_text_column,
        "indexed": indexed,
        "need_indexing": need_indexing,
        "total_with_text": indexed + need_indexing,
        "issue": None if has_extracted_text_column else "FTS5 table missing 'extracted_text' column. Run: POST /queue/fts/recreate",
    }


@router.post("/fts/recreate")
async def recreate_fts_table(db: DbSession) -> dict:
    """Recreate the FTS5 table with correct schema including extracted_text column."""
    from sqlalchemy import text
    
    try:
        # Drop existing table and triggers
        await db.execute(text("DROP TRIGGER IF EXISTS products_fts_insert"))
        await db.execute(text("DROP TRIGGER IF EXISTS products_fts_update"))
        await db.execute(text("DROP TRIGGER IF EXISTS products_fts_delete"))
        await db.execute(text("DROP TABLE IF EXISTS products_fts"))
        
        # Create with correct schema
        await db.execute(text("""
            CREATE VIRTUAL TABLE products_fts USING fts5(
                title,
                file_name,
                publisher,
                game_system,
                product_type,
                extracted_text
            )
        """))
        
        # Reset deep_indexed flag so items can be reprocessed
        await db.execute(text("UPDATE products SET deep_indexed = 0"))
        
        await db.commit()
        
        return {
            "success": True,
            "message": "FTS5 table recreated with extracted_text column. All products marked for re-indexing.",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@router.get("/text-extraction/stats")
async def get_text_extraction_stats(db: DbSession) -> dict:
    """Get text extraction queue statistics."""
    # Products needing extraction
    need_extraction_query = select(func.count()).select_from(Product).where(
        Product.text_extracted == False
    )
    need_result = await db.execute(need_extraction_query)
    need_extraction = need_result.scalar() or 0
    
    # Products already extracted
    extracted_query = select(func.count()).select_from(Product).where(
        Product.text_extracted == True
    )
    extracted_result = await db.execute(extracted_query)
    extracted = extracted_result.scalar() or 0
    
    # Queue stats for text tasks
    pending_query = select(func.count()).select_from(ProcessingQueue).where(
        ProcessingQueue.task_type == "text",
        ProcessingQueue.status == "pending"
    )
    pending_result = await db.execute(pending_query)
    pending = pending_result.scalar() or 0
    
    processing_query = select(func.count()).select_from(ProcessingQueue).where(
        ProcessingQueue.task_type == "text",
        ProcessingQueue.status == "processing"
    )
    processing_result = await db.execute(processing_query)
    processing = processing_result.scalar() or 0
    
    return {
        "need_extraction": need_extraction,
        "extracted": extracted,
        "total": need_extraction + extracted,
        "queue_pending": pending,
        "queue_processing": processing,
    }


@router.post("/{item_id}/retry")
async def retry_queue_item(
    db: DbSession,
    item_id: int,
) -> dict:
    """Retry a failed queue item."""
    query = select(ProcessingQueue).where(ProcessingQueue.id == item_id)
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    
    if item.status != "failed":
        raise HTTPException(
            status_code=400,
            detail="Can only retry failed items"
        )
    
    item.status = "pending"
    item.attempts = 0
    item.error_message = None
    item.started_at = None
    item.completed_at = None
    
    await db.commit()
    
    return {"retried": True, "id": item_id}


@router.post("/retry-all-failed")
async def retry_all_failed(
    db: DbSession,
    task_type: str | None = Query(None, description="Filter by task type"),
) -> dict:
    """Retry all failed queue items."""
    query = select(ProcessingQueue).where(ProcessingQueue.status == "failed")
    
    if task_type:
        query = query.where(ProcessingQueue.task_type == task_type)
    
    result = await db.execute(query)
    items = list(result.scalars().all())
    
    for item in items:
        item.status = "pending"
        item.attempts = 0
        item.error_message = None
        item.started_at = None
        item.completed_at = None
    
    await db.commit()
    
    return {
        "retried": len(items),
        "task_type_filter": task_type,
        "message": f"Reset {len(items)} failed items for retry",
    }


@router.post("/{item_id}/dismiss")
async def dismiss_queue_item(
    db: DbSession,
    item_id: int,
    mark_as_art: bool = Query(False, description="Mark product as art/maps (skip future text extraction)"),
) -> dict:
    """Dismiss a failed queue item permanently.
    
    Optionally marks the product as art/maps to skip future text extraction attempts.
    """
    query = select(ProcessingQueue).where(ProcessingQueue.id == item_id)
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    
    product_updated = False
    if mark_as_art:
        # Get the product and mark it as art/maps
        product_query = select(Product).where(Product.id == item.product_id)
        product_result = await db.execute(product_query)
        product = product_result.scalar_one_or_none()
        
        if product:
            if not product.product_type:
                product.product_type = "Art/Maps"
            # Mark text extraction as "done" to prevent future attempts
            product.text_extracted = True
            product_updated = True
    
    await db.delete(item)
    await db.commit()
    
    return {
        "dismissed": True,
        "id": item_id,
        "product_marked_as_art": product_updated,
    }


@router.post("/dismiss-all-failed")
async def dismiss_all_failed(
    db: DbSession,
    task_type: str | None = Query(None, description="Filter by task type"),
    mark_as_art: bool = Query(False, description="Mark products as art/maps"),
) -> dict:
    """Dismiss all failed queue items.
    
    Optionally marks products as art/maps to skip future text extraction.
    """
    query = select(ProcessingQueue).where(ProcessingQueue.status == "failed")
    
    if task_type:
        query = query.where(ProcessingQueue.task_type == task_type)
    
    result = await db.execute(query)
    items = list(result.scalars().all())
    
    products_marked = 0
    if mark_as_art:
        product_ids = [item.product_id for item in items]
        if product_ids:
            products_query = select(Product).where(Product.id.in_(product_ids))
            products_result = await db.execute(products_query)
            products = list(products_result.scalars().all())
            
            for product in products:
                if not product.product_type:
                    product.product_type = "Art/Maps"
                product.text_extracted = True
                products_marked += 1
    
    for item in items:
        await db.delete(item)
    
    await db.commit()
    
    return {
        "dismissed": len(items),
        "products_marked_as_art": products_marked,
        "task_type_filter": task_type,
    }


@router.delete("/{item_id}")
async def cancel_queue_item(
    db: DbSession,
    item_id: int,
) -> dict:
    """Cancel a pending queue item."""
    query = select(ProcessingQueue).where(ProcessingQueue.id == item_id)
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    
    if item.status not in ["pending"]:
        raise HTTPException(
            status_code=400,
            detail="Can only cancel pending items"
        )
    
    await db.delete(item)
    await db.commit()
    
    return {"deleted": True, "id": item_id}


@router.post("/deduplicate")
async def deduplicate_queue(db: DbSession) -> dict:
    """Remove duplicate pending queue items, keeping only the oldest per product+task."""
    from sqlalchemy import func, and_
    
    # Find duplicates: same product_id + task_type with status pending
    subquery = (
        select(
            ProcessingQueue.product_id,
            ProcessingQueue.task_type,
            func.min(ProcessingQueue.id).label("keep_id")
        )
        .where(ProcessingQueue.status == "pending")
        .group_by(ProcessingQueue.product_id, ProcessingQueue.task_type)
        .subquery()
    )
    
    # Get all pending items that are NOT the ones to keep
    duplicates_query = (
        select(ProcessingQueue)
        .where(ProcessingQueue.status == "pending")
        .where(
            ~ProcessingQueue.id.in_(
                select(subquery.c.keep_id)
            )
        )
    )
    
    result = await db.execute(duplicates_query)
    duplicates = list(result.scalars().all())
    
    for item in duplicates:
        await db.delete(item)
    
    await db.commit()
    
    return {"removed": len(duplicates), "message": f"Removed {len(duplicates)} duplicate queue items"}


@router.delete("")
async def clear_completed(
    db: DbSession,
    status: str = Query("completed", description="Status to clear"),
) -> dict:
    """Clear completed or failed items from the queue."""
    if status not in ["completed", "failed", "pending"]:
        raise HTTPException(
            status_code=400,
            detail="Status must be completed, failed, or pending"
        )
    
    query = select(ProcessingQueue).where(ProcessingQueue.status == status)
    result = await db.execute(query)
    items = list(result.scalars().all())
    
    for item in items:
        await db.delete(item)
    
    await db.commit()
    
    return {"cleared": len(items), "status": status}


@router.post("/deduplicate")
async def deduplicate_queue(
    db: DbSession,
) -> dict:
    """Remove duplicate pending queue items, keeping only the oldest per product+task_type."""
    # Find duplicates: same product_id + task_type with status=pending
    # Keep the one with lowest id (oldest), delete the rest
    result = await db.execute(
        text("""
            DELETE FROM processing_queue
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM processing_queue
                WHERE status = 'pending'
                GROUP BY product_id, task_type
            )
            AND status = 'pending'
        """)
    )
    deleted = result.rowcount
    await db.commit()
    
    return {"deleted": deleted, "message": f"Removed {deleted} duplicate queue items"}


@router.post("/process")
async def process_queue_items(
    max_items: int = Query(10, ge=1, le=100000, description="Max items to process"),
) -> dict:
    """Process pending items in the queue."""
    from grimoire.services.queue_processor import process_queue
    
    result = await process_queue(max_items=max_items, delay=0.1)
    return result


@router.post("/{item_id}/process")
async def process_single_item(
    item_id: int,
) -> dict:
    """Process a single queue item immediately."""
    from grimoire.services.queue_processor import process_queue_item
    
    success = await process_queue_item(item_id)
    return {"success": success, "item_id": item_id}
