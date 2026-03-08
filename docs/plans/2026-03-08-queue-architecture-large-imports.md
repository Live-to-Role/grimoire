# Queue Architecture for Large Library Imports

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the queue system so that importing 1,000+ PDFs processes efficiently without blocking the UI, starving lightweight tasks, or causing SQLite contention — while giving users clear real-time progress feedback.

**Architecture:** Replace the single serial poll-loop queue worker with a concurrent, priority-aware worker that runs CPU-heavy tasks (cover extraction, text extraction, OCR) in a thread pool via `asyncio.to_thread()`. Add a global semaphore to cap total concurrent work across all queues. Switch the frontend from polling to Server-Sent Events (SSE) for instant progress updates. Keep SQLite (no Postgres migration needed).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (async), SQLite/aiosqlite, asyncio (Semaphore, to_thread), React 18, TypeScript, React Query v5, EventSource API

**Relationship to existing plan:** The [2026-03-08-performance-improvements.md](./2026-03-08-performance-improvements.md) plan covers query optimization, debouncing, and specific bottleneck fixes. This plan covers the queue worker architecture, cross-queue coordination, and real-time UX. Some overlap exists with Tasks 4, 5, and 11 from that plan — this plan supersedes those tasks.

---

## Task 1: Run blocking task handlers in thread pool

**Priority:** CRITICAL — This is the single biggest issue. Every sync PDF operation (fitz, PIL, Tesseract, file I/O) runs directly in the async event loop, blocking ALL other async work (API responses, DB queries, the other queue) for seconds to minutes per task.

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py:28-36` (handle_cover_task)
- Modify: `backend/grimoire/services/queue_processor.py:76-113` (handle_text_task)
- Modify: `backend/grimoire/services/queue_processor.py:116-180` (handle_ocr_text_task)
- Modify: `backend/grimoire/services/queue_processor.py:206-246` (handle_embed_task)
- Test: `backend/tests/services/test_queue_processor.py`

**Problem:** `process_cover_sync()`, `process_text_extraction_sync()`, `extract_with_ocr()`, and `get_extracted_text()` are all synchronous functions that do heavy file I/O, PDF rendering, and CPU work. They're called directly from async handlers, which means the single event loop thread is occupied for the entire duration. During a large import with `batch_size=3`, three of these can pile up and the API becomes unresponsive.

**Step 1: Write the failing test**

Create `backend/tests/__init__.py` (empty), `backend/tests/services/__init__.py` (empty), then create `backend/tests/services/test_queue_processor.py`:

```python
"""Tests for queue processor thread offloading."""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_cover_task_runs_in_thread():
    """Cover extraction must not block the event loop."""
    from grimoire.services.queue_processor import handle_cover_task

    product = MagicMock()
    product.id = 1
    db = AsyncMock()

    with patch(
        "grimoire.services.queue_processor.process_cover_sync", return_value=True
    ) as mock_sync, patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = True
        # After refactor, handle_cover_task should call asyncio.to_thread
        await handle_cover_task(db, product)
        mock_thread.assert_called_once_with(mock_sync, product)


@pytest.mark.asyncio
async def test_text_task_runs_in_thread():
    """Text extraction must not block the event loop."""
    from grimoire.services.queue_processor import handle_text_task

    product = MagicMock()
    product.id = 1
    product.file_path = "/fake/path.pdf"
    db = AsyncMock()

    with patch(
        "grimoire.services.queue_processor.detect_needs_ocr",
        return_value={"needs_ocr": False},
    ), patch(
        "grimoire.services.queue_processor.process_text_extraction_sync",
        return_value=True,
    ) as mock_sync, patch(
        "asyncio.to_thread", new_callable=AsyncMock
    ) as mock_thread, patch(
        "grimoire.services.queue_processor.update_search_vector",
        new_callable=AsyncMock,
    ), patch(
        "grimoire.services.queue_processor.queue_ai_identify_if_enabled",
        new_callable=AsyncMock,
    ), patch("pathlib.Path.exists", return_value=True):
        mock_thread.return_value = True
        await handle_text_task(db, product)
        # to_thread should be called for the sync extraction
        assert mock_thread.called


@pytest.mark.asyncio
async def test_event_loop_not_blocked_during_sync_task():
    """Verify that the event loop remains responsive while a sync task runs."""
    import time

    async def check_loop_responsive():
        """This coroutine should complete promptly if the loop isn't blocked."""
        start = asyncio.get_event_loop().time()
        await asyncio.sleep(0)  # yield to event loop
        elapsed = asyncio.get_event_loop().time() - start
        return elapsed < 0.1  # should be near-instant

    def slow_sync_work():
        time.sleep(0.2)
        return True

    # Run slow work in thread - loop should stay responsive
    task = asyncio.create_task(asyncio.to_thread(slow_sync_work))
    responsive = await check_loop_responsive()
    await task

    assert responsive, "Event loop was blocked during sync work"
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/services/test_queue_processor.py -v`
Expected: `test_cover_task_runs_in_thread` FAILS because current code calls `process_cover_sync()` directly, not via `asyncio.to_thread()`.

**Step 3: Refactor handlers to use asyncio.to_thread()**

In `backend/grimoire/services/queue_processor.py`, update each handler that calls sync code:

```python
@register_handler("cover")
async def handle_cover_task(db: AsyncSession, product: Product) -> bool:
    """Handle cover extraction task."""
    from grimoire.services.processor import process_cover_sync

    success = await asyncio.to_thread(process_cover_sync, product)
    if success:
        await db.commit()
    return success


@register_handler("text")
async def handle_text_task(db: AsyncSession, product: Product) -> bool:
    """Handle text extraction task.

    If the PDF is detected as image-based (needs OCR), queues an ocr_text task instead.
    After successful extraction, queues AI identification if enabled.
    """
    from grimoire.services.processor import process_text_extraction_sync
    from grimoire.services.fts_service import update_search_vector
    from grimoire.processors.text_extractor import detect_needs_ocr

    pdf_path = Path(product.file_path)
    if pdf_path.exists():
        # detect_needs_ocr opens PDF with fitz — run in thread
        detection = await asyncio.to_thread(detect_needs_ocr, pdf_path)
        if detection["needs_ocr"]:
            ocr_item = ProcessingQueue(
                product_id=product.id,
                task_type="ocr_text",
                priority=1,
                status="pending",
            )
            db.add(ocr_item)
            await db.commit()
            logger.info(f"Product {product.id} needs OCR: {detection['reason']}")
            return True

    # Run sync extraction in thread pool
    success = await asyncio.to_thread(process_text_extraction_sync, product, False)
    if success:
        await db.commit()
        await update_search_vector(db, product)
        await queue_ai_identify_if_enabled(db, product)
        await db.commit()
    return success


@register_handler("ocr_text")
async def handle_ocr_text_task(db: AsyncSession, product: Product) -> bool:
    """Handle OCR text extraction task for image-based PDFs."""
    from grimoire.services.fts_service import update_search_vector
    from grimoire.processors.text_extractor import extract_with_ocr, TESSERACT_AVAILABLE
    from grimoire.config import settings
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
            text_dir = settings.data_dir / "text"
            text_dir.mkdir(parents=True, exist_ok=True)
            text_file = text_dir / f"{product.id}.json"

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

            return str(text_file), total_pages

        text_file_path, _ = await asyncio.to_thread(_save_ocr_result)

        product.extracted_text_path = text_file_path
        product.text_extracted = True
        await db.commit()

        await update_search_vector(db, product)
        await queue_ai_identify_if_enabled(db, product)
        await db.commit()

        logger.info(
            f"OCR extraction completed for product {product.id}: "
            f"{len(markdown_text)} chars"
        )
        return True

    except Exception as e:
        logger.error(f"OCR extraction failed for product {product.id}: {e}")
        return False


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
        await db.execute(
            delete(ProductEmbedding).where(ProductEmbedding.product_id == product.id)
        )

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
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/services/test_queue_processor.py -v`
Expected: All 3 tests PASS.

**Step 5: Commit**

```bash
git add backend/tests/ backend/grimoire/services/queue_processor.py
git commit -m "perf: run blocking PDF/OCR/embed handlers in thread pool via asyncio.to_thread"
```

---

## Task 2: Add global concurrency semaphore to the queue worker

**Priority:** HIGH — Without a concurrency limit, the worker processes items sequentially (one at a time via `process_queue` loop). With `to_thread` from Task 1, we can now safely run multiple tasks concurrently, but need to cap them to avoid overwhelming the system.

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py:457-529` (process_queue and run_queue_worker)
- Modify: `backend/grimoire/config.py:38` (max_concurrent_processing)
- Test: `backend/tests/services/test_queue_worker.py`

**Problem:** The current `process_queue()` function processes items in a serial loop — fetch one item, process it, fetch the next. Even with `batch_size=3`, items are processed one at a time with a 0.1s delay between them. After Task 1 offloads sync work to threads, we can safely run multiple tasks concurrently. But we need a semaphore to prevent launching 50 cover extractions simultaneously.

**Step 1: Write the failing test**

Create `backend/tests/services/test_queue_worker.py`:

```python
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

    original_process = None

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
        # Mock DB to return 5 pending items then none
        mock_db = AsyncMock()
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
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/services/test_queue_worker.py -v`
Expected: FAIL — `run_queue_worker` doesn't accept `max_concurrent` param, and `get_pending_batch` doesn't exist.

**Step 3: Refactor run_queue_worker for concurrent batch processing**

Replace the bottom section of `backend/grimoire/services/queue_processor.py` (the `get_next_pending_item`, `process_queue`, and `run_queue_worker` functions) with:

```python
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

            # If we got a full batch, immediately poll again (more items likely)
            if len(items) >= batch_size:
                continue

        except Exception as e:
            logger.error(f"Queue worker error: {e}")

        await asyncio.sleep(poll_interval)
```

Also keep `get_next_pending_item` for backward compatibility if used elsewhere, but the worker no longer uses it.

**Step 4: Update main.py to use new parameters**

In `backend/grimoire/main.py`, update the queue worker start:

```python
    queue_task = asyncio.create_task(
        run_queue_worker(
            poll_interval=2.0,
            batch_size=10,
            stop_event=queue_stop_event,
        )
    )
```

The `max_concurrent` will default to `settings.max_concurrent_processing` (currently 3). Users can raise it via env var `MAX_CONCURRENT_PROCESSING=5`.

**Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/services/test_queue_worker.py -v`
Expected: Both tests PASS.

**Step 6: Commit**

```bash
git add backend/grimoire/services/queue_processor.py backend/grimoire/main.py backend/tests/
git commit -m "perf: concurrent queue worker with semaphore-based concurrency control"
```

---

## Task 3: Prioritize task types to prevent starvation during large imports

**Priority:** HIGH — During a large import, thousands of cover tasks flood the queue and block text extraction, AI identification, and FTS indexing from ever running until all covers are done.

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py` (get_pending_batch)
- Modify: `backend/grimoire/services/scanner.py:206-293` (queue_products_for_processing)
- Test: `backend/tests/services/test_queue_priority.py`

**Problem:** The scanner queues cover tasks at priority 3, text at priority 5, and AI identify at priority 7. Higher priority number = processed first. This means during a 1,000-PDF import, all 1,000 text extraction tasks run before any covers, and all AI identify tasks run before text extraction. This is backwards — users want to see covers immediately in the UI.

Additionally, the current `get_pending_batch` just grabs the top N items by priority, so a flood of one task type starves all others.

**Step 1: Write the failing test**

Create `backend/tests/services/test_queue_priority.py`:

```python
"""Tests for queue priority and fair scheduling."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch

from grimoire.models.queue import ProcessingQueue


@pytest.mark.asyncio
async def test_batch_includes_mix_of_task_types():
    """When queue has many covers and some text tasks, batch should include both."""
    from grimoire.services.queue_processor import get_pending_batch

    # Create mock items: 20 covers (priority 8) and 5 text (priority 5)
    cover_items = [
        ProcessingQueue(
            id=i, product_id=i, task_type="cover",
            priority=8, status="pending", created_at=datetime.now(UTC),
        )
        for i in range(1, 21)
    ]
    text_items = [
        ProcessingQueue(
            id=i + 20, product_id=i + 20, task_type="text",
            priority=5, status="pending", created_at=datetime.now(UTC),
        )
        for i in range(1, 6)
    ]

    all_items = cover_items + text_items

    db = AsyncMock()

    # Mock the query to return items sorted by priority desc
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = all_items[:10]
    db.execute = AsyncMock(return_value=mock_result)

    batch = await get_pending_batch(db, batch_size=10)
    task_types = {item.task_type for item in batch}

    # With fair scheduling, batch should not be 100% covers
    # (This test documents the DESIRED behavior after refactoring)
    assert len(batch) == 10


@pytest.mark.asyncio
async def test_cover_tasks_have_highest_priority():
    """Cover extraction should have highest priority (users see covers in UI)."""
    # Verify the priority constants
    COVER_PRIORITY = 8  # highest — visible to user immediately
    TEXT_PRIORITY = 5
    AI_IDENTIFY_PRIORITY = 3
    OCR_PRIORITY = 1  # lowest — very slow

    assert COVER_PRIORITY > TEXT_PRIORITY > AI_IDENTIFY_PRIORITY > OCR_PRIORITY
```

**Step 2: Run test to verify current state**

Run: `cd backend && python -m pytest tests/services/test_queue_priority.py -v`

**Step 3: Fix priority values in scanner**

The current priorities are inverted for UX. Fix `backend/grimoire/services/scanner.py` in `queue_products_for_processing`:

```python
    for product in products:
        if product.is_duplicate:
            continue

        # Queue for cover extraction — highest priority (visible in UI immediately)
        if not product.cover_extracted:
            existing = await db.execute(
                select(ProcessingQueue).where(
                    ProcessingQueue.product_id == product.id,
                    ProcessingQueue.task_type == "cover",
                    ProcessingQueue.status.in_(["pending", "processing"])
                )
            )
            if not existing.scalar_one_or_none():
                queue_item = ProcessingQueue(
                    product_id=product.id,
                    task_type="cover",
                    priority=8,  # Was 3 — covers should be first (user sees them)
                    status="pending",
                )
                db.add(queue_item)
                queued_covers += 1

        # Queue for text extraction
        if auto_extract_text and not product.text_extracted:
            existing = await db.execute(
                select(ProcessingQueue).where(
                    ProcessingQueue.product_id == product.id,
                    ProcessingQueue.task_type == "text",
                    ProcessingQueue.status.in_(["pending", "processing"])
                )
            )
            if not existing.scalar_one_or_none():
                queue_item = ProcessingQueue(
                    product_id=product.id,
                    task_type="text",
                    priority=5,
                    status="pending",
                )
                db.add(queue_item)
                queued_text += 1

        # Queue for AI identification
        if auto_identify and product.text_extracted and not product.ai_identified:
            existing = await db.execute(
                select(ProcessingQueue).where(
                    ProcessingQueue.product_id == product.id,
                    ProcessingQueue.task_type == "ai_identify",
                    ProcessingQueue.status.in_(["pending", "processing"])
                )
            )
            if not existing.scalar_one_or_none():
                queue_item = ProcessingQueue(
                    product_id=product.id,
                    task_type="ai_identify",
                    priority=3,
                    status="pending",
                )
                db.add(queue_item)
```

Also fix `queue_ai_identify_if_enabled` in `queue_processor.py` — confirm it uses priority=3 (it already does).

And fix the OCR queueing in `handle_text_task` — confirm it uses priority=1 (it already does).

**Step 4: Run tests**

Run: `cd backend && python -m pytest tests/services/test_queue_priority.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/grimoire/services/scanner.py backend/grimoire/services/queue_processor.py backend/tests/
git commit -m "perf: fix task priority order — covers first for immediate UX feedback"
```

---

## Task 4: Batch queue insertion to reduce SQLite write contention during scanning

**Priority:** MEDIUM — During a large import, the scanner issues individual INSERT + SELECT (dedup check) per product per task type, causing hundreds of small transactions that contend with the queue worker's reads.

**Files:**
- Modify: `backend/grimoire/services/scanner.py:206-293` (queue_products_for_processing)
- Test: `backend/tests/services/test_scanner_batch.py`

**Problem:** `queue_products_for_processing` loops over each product and, for each task type, runs a SELECT to check for existing queue items, then INSERTs if needed. For 1,000 products with 2 task types enabled, that's 2,000 SELECT queries + up to 2,000 INSERTs. This hammers SQLite with small transactions during a scan.

**Step 1: Write the failing test**

Create `backend/tests/services/test_scanner_batch.py`:

```python
"""Tests for batch queue insertion during scanning."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_queue_products_uses_batch_insert():
    """Queue insertion should batch products instead of one-by-one INSERT+SELECT."""
    from grimoire.services.scanner import queue_products_for_processing

    products = []
    for i in range(100):
        p = MagicMock()
        p.id = i + 1
        p.is_duplicate = False
        p.cover_extracted = False
        p.text_extracted = False
        p.ai_identified = False
        products.append(p)

    db = AsyncMock()

    # Mock settings to enable text extraction
    with patch(
        "grimoire.services.scanner.get_scan_settings",
        new_callable=AsyncMock,
        return_value={"auto_extract_text_on_scan": True, "auto_identify_on_scan": False},
    ):
        # Mock the existing queue check to return no existing items
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        result = await queue_products_for_processing(db, products)

    # Should have queued covers and text for all 100 products
    assert result["covers"] == 100
    assert result["text"] == 100

    # Key assertion: db.commit should be called a small number of times (batched),
    # not 200 times (once per item per task type)
    assert db.commit.call_count <= 3, (
        f"Expected batched commits but got {db.commit.call_count} commits"
    )
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/services/test_scanner_batch.py -v`
Expected: FAIL — current code does a SELECT per product per task type and commits per batch of products.

**Step 3: Refactor queue_products_for_processing to batch**

Replace `queue_products_for_processing` in `backend/grimoire/services/scanner.py`:

```python
async def queue_products_for_processing(db: AsyncSession, products: list[Product]) -> dict:
    """Queue products for processing based on settings.

    Uses batch queries to check for existing queue items instead of
    per-product SELECTs, and inserts all new queue items in one transaction.

    Args:
        db: Database session
        products: List of products to check and queue

    Returns:
        Dict with queued counts per task type
    """
    from grimoire.models import ProcessingQueue

    settings_dict = await get_scan_settings(db)
    auto_extract_text = settings_dict.get("auto_extract_text_on_scan", False)
    auto_identify = settings_dict.get("auto_identify_on_scan", False)

    # Filter out duplicates
    eligible = [p for p in products if not p.is_duplicate]
    if not eligible:
        return {"covers": 0, "text": 0}

    product_ids = [p.id for p in eligible]

    # Batch query: find all existing pending/processing queue items for these products
    existing_query = (
        select(ProcessingQueue.product_id, ProcessingQueue.task_type)
        .where(
            ProcessingQueue.product_id.in_(product_ids),
            ProcessingQueue.status.in_(["pending", "processing"]),
        )
    )
    existing_result = await db.execute(existing_query)
    existing_set = {(row[0], row[1]) for row in existing_result.all()}

    queued_covers = 0
    queued_text = 0

    for product in eligible:
        if not product.cover_extracted and (product.id, "cover") not in existing_set:
            db.add(ProcessingQueue(
                product_id=product.id,
                task_type="cover",
                priority=8,
                status="pending",
            ))
            queued_covers += 1

        if auto_extract_text and not product.text_extracted and (product.id, "text") not in existing_set:
            db.add(ProcessingQueue(
                product_id=product.id,
                task_type="text",
                priority=5,
                status="pending",
            ))
            queued_text += 1

        if auto_identify and product.text_extracted and not product.ai_identified and (product.id, "ai_identify") not in existing_set:
            db.add(ProcessingQueue(
                product_id=product.id,
                task_type="ai_identify",
                priority=3,
                status="pending",
            ))

    if queued_covers > 0 or queued_text > 0:
        await db.commit()

    return {"covers": queued_covers, "text": queued_text}
```

**Step 4: Run test**

Run: `cd backend && python -m pytest tests/services/test_scanner_batch.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/grimoire/services/scanner.py backend/tests/
git commit -m "perf: batch queue insertion during scan — single query instead of N per product"
```

---

## Task 5: Add Server-Sent Events (SSE) for real-time queue progress

**Priority:** MEDIUM — The frontend polls queue stats every 3 seconds and scan status every 2 seconds. During a large import this creates unnecessary load and still has 2-3 second latency for progress updates. SSE gives instant updates and eliminates polling overhead.

**Files:**
- Create: `backend/grimoire/services/event_bus.py`
- Modify: `backend/grimoire/api/routes/queue.py` (add SSE endpoint)
- Modify: `backend/grimoire/services/queue_processor.py` (emit events on task completion)
- Modify: `frontend/src/api/client.ts` (add EventSource helper)
- Modify: `frontend/src/components/ProcessingQueue.tsx` (replace polling with SSE)
- Test: `backend/tests/services/test_event_bus.py`

**Problem:** The frontend polls `/queue/stats` every 3s and `/library/scan/status` every 2s. During a 1,000-PDF import, this means:
- 20 polls/minute for queue stats alone
- 2-3 second delay before user sees progress update
- Wasted requests when nothing changed
- Extra DB queries on every poll

**Step 1: Write the failing test for event bus**

Create `backend/tests/services/test_event_bus.py`:

```python
"""Tests for the in-process event bus."""

import asyncio
import pytest


@pytest.mark.asyncio
async def test_event_bus_publishes_to_subscribers():
    """Subscribers should receive events published after they subscribe."""
    from grimoire.services.event_bus import event_bus

    received = []

    async def collect_events():
        async for event in event_bus.subscribe("queue"):
            received.append(event)
            if len(received) >= 2:
                break

    task = asyncio.create_task(collect_events())

    await asyncio.sleep(0.01)  # let subscriber register
    await event_bus.publish("queue", {"type": "task_completed", "id": 1})
    await event_bus.publish("queue", {"type": "task_completed", "id": 2})

    await asyncio.wait_for(task, timeout=1.0)

    assert len(received) == 2
    assert received[0]["id"] == 1
    assert received[1]["id"] == 2


@pytest.mark.asyncio
async def test_event_bus_multiple_subscribers():
    """Multiple subscribers should each receive the same events."""
    from grimoire.services.event_bus import event_bus

    received_a = []
    received_b = []

    async def collect_a():
        async for event in event_bus.subscribe("queue"):
            received_a.append(event)
            if len(received_a) >= 1:
                break

    async def collect_b():
        async for event in event_bus.subscribe("queue"):
            received_b.append(event)
            if len(received_b) >= 1:
                break

    task_a = asyncio.create_task(collect_a())
    task_b = asyncio.create_task(collect_b())

    await asyncio.sleep(0.01)
    await event_bus.publish("queue", {"type": "task_completed", "id": 1})

    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)

    assert len(received_a) == 1
    assert len(received_b) == 1


@pytest.mark.asyncio
async def test_event_bus_unsubscribe_on_disconnect():
    """When a subscriber breaks out of the loop, it should be cleaned up."""
    from grimoire.services.event_bus import event_bus

    initial_count = len(event_bus._subscribers.get("queue", []))

    async for event in event_bus.subscribe("queue"):
        break  # immediately disconnect

    # Give cleanup a moment
    await asyncio.sleep(0.01)

    final_count = len(event_bus._subscribers.get("queue", []))
    assert final_count == initial_count  # subscriber should be removed
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/services/test_event_bus.py -v`
Expected: FAIL — `event_bus` module doesn't exist.

**Step 3: Create the event bus**

Create `backend/grimoire/services/event_bus.py`:

```python
"""In-process async event bus for real-time notifications via SSE."""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    """Simple pub/sub event bus using asyncio.Queue per subscriber.

    Channels isolate event types (e.g. "queue", "scan") so subscribers
    only receive events they care about.
    """

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        """Publish an event to all subscribers of a channel."""
        queues = self._subscribers.get(channel, [])
        dead = []
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)

        # Remove dead subscribers
        for q in dead:
            queues.remove(q)

    async def subscribe(self, channel: str):
        """Async generator that yields events for a channel.

        Usage:
            async for event in event_bus.subscribe("queue"):
                yield f"data: {json.dumps(event)}\\n\\n"
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(channel, []).append(q)
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            # Cleanup on disconnect
            subs = self._subscribers.get(channel, [])
            if q in subs:
                subs.remove(q)


# Global singleton
event_bus = EventBus()
```

**Step 4: Run tests**

Run: `cd backend && python -m pytest tests/services/test_event_bus.py -v`
Expected: PASS.

**Step 5: Add SSE endpoint to queue routes**

Find the queue routes file and add the SSE endpoint. First, locate it:

Look for `backend/grimoire/api/routes/queue.py`. Add this endpoint:

```python
from fastapi.responses import StreamingResponse
from grimoire.services.event_bus import event_bus
import json


@router.get("/queue/events")
async def queue_events():
    """Server-Sent Events stream for real-time queue progress updates.

    Events:
    - task_completed: {id, task_type, product_id}
    - task_failed: {id, task_type, product_id, error}
    - batch_complete: {succeeded, failed, total}
    - stats_update: {pending, processing, completed, failed}
    """

    async def event_stream():
        async for event in event_bus.subscribe("queue"):
            data = json.dumps(event)
            yield f"data: {data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

**Step 6: Emit events from queue processor**

In `backend/grimoire/services/queue_processor.py`, add event publishing at key points in `process_queue_item()`:

After a task completes or fails (around line 400-427):

```python
from grimoire.services.event_bus import event_bus

# Inside process_queue_item, after success:
await event_bus.publish("queue", {
    "type": "task_completed",
    "id": item.id,
    "task_type": item.task_type,
    "product_id": item.product_id,
})

# Inside process_queue_item, after failure:
await event_bus.publish("queue", {
    "type": "task_failed",
    "id": item.id,
    "task_type": item.task_type,
    "product_id": item.product_id,
    "error": str(e)[:200] if isinstance(e, Exception) else item.error_message,
})
```

In `run_queue_worker`, after each batch completes:

```python
await event_bus.publish("queue", {
    "type": "batch_complete",
    "succeeded": succeeded,
    "failed": failed,
    "total": len(items),
})
```

**Step 7: Commit**

```bash
git add backend/grimoire/services/event_bus.py backend/grimoire/api/routes/queue.py backend/grimoire/services/queue_processor.py backend/tests/
git commit -m "feat: add SSE event bus for real-time queue progress notifications"
```

---

## Task 6: Frontend — connect to SSE and reduce polling

**Priority:** MEDIUM — Completes the SSE pipeline from Task 5. Without this, the frontend still polls every 3 seconds.

**Files:**
- Create: `frontend/src/hooks/useQueueEvents.ts`
- Modify: `frontend/src/components/ProcessingQueue.tsx` (use SSE, reduce poll frequency)

**Step 1: Create the SSE hook**

Create `frontend/src/hooks/useQueueEvents.ts`:

```typescript
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

interface QueueEvent {
  type:
    | "task_completed"
    | "task_failed"
    | "batch_complete"
    | "stats_update";
  id?: number;
  task_type?: string;
  product_id?: number;
  error?: string;
  succeeded?: number;
  failed?: number;
  total?: number;
}

/**
 * Hook that connects to the queue SSE endpoint and invalidates
 * React Query caches when events arrive. Falls back to polling
 * if SSE is unavailable.
 */
export function useQueueEvents() {
  const queryClient = useQueryClient();
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const es = new EventSource("/api/v1/queue/events");
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data: QueueEvent = JSON.parse(event.data);

        // Invalidate queue stats on any event
        queryClient.invalidateQueries({ queryKey: ["queueStats"] });

        // On task completion, also invalidate the specific product
        if (
          data.type === "task_completed" &&
          data.product_id
        ) {
          queryClient.invalidateQueries({
            queryKey: ["product", data.product_id],
          });

          // If a cover was extracted, invalidate product list for thumbnail
          if (data.task_type === "cover") {
            queryClient.invalidateQueries({ queryKey: ["products"] });
          }
        }

        // On batch complete, invalidate queue items list
        if (data.type === "batch_complete") {
          queryClient.invalidateQueries({ queryKey: ["queueItems"] });
        }
      } catch {
        // Ignore parse errors
      }
    };

    es.onerror = () => {
      // SSE disconnected — React Query polling will take over as fallback
      es.close();
    };

    return () => {
      es.close();
    };
  }, [queryClient]);
}
```

**Step 2: Update ProcessingQueue.tsx to use SSE**

In `frontend/src/components/ProcessingQueue.tsx`, add the hook and reduce polling frequency:

At the top of the component:
```typescript
import { useQueueEvents } from "../hooks/useQueueEvents";
```

Inside the component function, add:
```typescript
// SSE connection for real-time updates (falls back to polling below)
useQueueEvents();
```

Change the `refetchInterval` for queue stats and items from `3000` to `30000` (30 seconds as fallback):
```typescript
refetchInterval: 30000,  // Was 3000 — SSE handles real-time, this is just fallback
```

**Step 3: Commit**

```bash
git add frontend/src/hooks/useQueueEvents.ts frontend/src/components/ProcessingQueue.tsx
git commit -m "feat: frontend SSE integration for real-time queue progress, reduce polling"
```

---

## Task 7: Cache settings lookups in queue processor

**Priority:** LOW — Each task handler calls `get_setting()` which queries the DB. During a batch of 10 tasks, that's 10 redundant queries for the same settings that rarely change.

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py:39-51` (get_setting)
- Test: `backend/tests/services/test_settings_cache.py`

**Problem:** `get_setting("auto_identify_on_scan")` is called for every text extraction and OCR task. During a 1,000-PDF import, that's 1,000+ identical DB queries for a setting that changes maybe once a month.

**Step 1: Write the failing test**

Create `backend/tests/services/test_settings_cache.py`:

```python
"""Tests for settings caching in queue processor."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_get_setting_caches_result():
    """Repeated calls to get_setting should not hit the database each time."""
    from grimoire.services.queue_processor import get_setting, _settings_cache

    db = AsyncMock()

    # First call should query DB
    mock_setting = MagicMock()
    mock_setting.value = '"test_value"'
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none.return_value = mock_setting
    db.execute = AsyncMock(return_value=mock_result)

    # Clear cache before test
    _settings_cache.clear()

    result1 = await get_setting(db, "test_key")
    assert result1 == "test_value"
    assert db.execute.call_count == 1

    # Second call should use cache
    result2 = await get_setting(db, "test_key")
    assert result2 == "test_value"
    assert db.execute.call_count == 1  # no additional DB call
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/services/test_settings_cache.py -v`
Expected: FAIL — `_settings_cache` doesn't exist.

**Step 3: Add TTL cache to get_setting**

In `backend/grimoire/services/queue_processor.py`, replace `get_setting`:

```python
import time

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
```

**Step 4: Run test**

Run: `cd backend && python -m pytest tests/services/test_settings_cache.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/grimoire/services/queue_processor.py backend/tests/
git commit -m "perf: add 60s TTL cache for settings lookups in queue processor"
```

---

## Task 8: Add queue progress summary to scan status API

**Priority:** LOW — After a scan completes, the user sees "Scan complete: 500 new products" but has no idea how long processing will take. Adding queue depth to the scan status response gives context.

**Files:**
- Modify: `backend/grimoire/api/routes/queue.py` (enhance stats endpoint)
- Modify: `frontend/src/pages/LibraryManagement.tsx` (show processing ETA)

**Step 1: Enhance queue stats endpoint**

In the queue stats endpoint, add task-type breakdown and estimated time:

```python
@router.get("/queue/stats")
async def get_queue_stats(db: AsyncSession = Depends(get_db)):
    """Get queue statistics with per-task-type breakdown."""
    from sqlalchemy import func

    # Overall stats
    stats_query = select(
        ProcessingQueue.status,
        func.count(ProcessingQueue.id),
    ).group_by(ProcessingQueue.status)
    result = await db.execute(stats_query)
    stats = {row[0]: row[1] for row in result.all()}

    # Per-task-type pending counts
    type_query = select(
        ProcessingQueue.task_type,
        func.count(ProcessingQueue.id),
    ).where(
        ProcessingQueue.status == "pending"
    ).group_by(ProcessingQueue.task_type)
    type_result = await db.execute(type_query)
    pending_by_type = {row[0]: row[1] for row in type_result.all()}

    return {
        "pending": stats.get("pending", 0),
        "processing": stats.get("processing", 0),
        "completed": stats.get("completed", 0),
        "failed": stats.get("failed", 0),
        "pending_by_type": pending_by_type,
    }
```

**Step 2: Show pending breakdown in frontend**

In `frontend/src/pages/LibraryManagement.tsx`, in the processing tab, display the pending breakdown:

```typescript
{queueStats?.pending_by_type && Object.keys(queueStats.pending_by_type).length > 0 && (
  <div className="text-sm text-gray-500 mt-1">
    {Object.entries(queueStats.pending_by_type).map(([type, count]) => (
      <span key={type} className="mr-3">
        {type}: {count}
      </span>
    ))}
  </div>
)}
```

**Step 3: Commit**

```bash
git add backend/grimoire/api/routes/queue.py frontend/src/pages/LibraryManagement.tsx
git commit -m "feat: add per-task-type breakdown to queue stats for better progress visibility"
```

---

## Task 9: Prevent scanner from blocking the event loop during large folder walks

**Priority:** MEDIUM — `folder_path.rglob("*.pdf")` and `calculate_file_hash()` are synchronous file I/O operations. On a network drive or large folder (10,000+ files), `rglob` can take minutes and blocks the entire event loop.

**Files:**
- Modify: `backend/grimoire/services/scanner.py:19-36` (calculate_file_hash)
- Modify: `backend/grimoire/services/scanner.py:44-183` (scan_folder)
- Test: `backend/tests/services/test_scanner_async.py`

**Step 1: Write the failing test**

Create `backend/tests/services/test_scanner_async.py`:

```python
"""Tests for non-blocking scanner operations."""

import asyncio
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_file_hash_does_not_block_event_loop():
    """calculate_file_hash should run file I/O in a thread."""
    import tempfile
    import os
    from pathlib import Path

    # Create a temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
        f.write(b"x" * 1024)
        temp_path = Path(f.name)

    try:
        from grimoire.services.scanner import calculate_file_hash

        # Verify it still works
        result = await calculate_file_hash(temp_path)
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest

        # Verify event loop stays responsive during hash
        async def check_responsive():
            start = asyncio.get_event_loop().time()
            await asyncio.sleep(0)
            return asyncio.get_event_loop().time() - start < 0.05

        responsive = await check_responsive()
        assert responsive
    finally:
        os.unlink(temp_path)
```

**Step 2: Run test**

Run: `cd backend && python -m pytest tests/services/test_scanner_async.py -v`

**Step 3: Wrap blocking scanner operations in asyncio.to_thread**

In `backend/grimoire/services/scanner.py`:

```python
async def calculate_file_hash(file_path: Path, max_bytes: int = 1024 * 1024) -> str:
    """Calculate SHA-256 hash of file header for fast identification.

    Runs file I/O in a thread to avoid blocking the async event loop.
    """
    def _hash_sync():
        sha256_hash = hashlib.sha256()
        file_size = file_path.stat().st_size
        sha256_hash.update(str(file_size).encode())
        with open(file_path, "rb") as f:
            data = f.read(max_bytes)
            sha256_hash.update(data)
        return sha256_hash.hexdigest()

    return await asyncio.to_thread(_hash_sync)
```

Add `import asyncio` to the top of scanner.py.

For the `rglob` call in `scan_folder`, wrap the directory listing in a thread:

```python
    # Collect PDF paths in a thread to avoid blocking on large/network folders
    pdf_paths = await asyncio.to_thread(
        lambda: [p for p in folder_path.rglob("*.pdf") if p.is_file()]
    )

    for pdf_path in pdf_paths:
        # ... rest of loop unchanged
```

Remove the `if not pdf_path.is_file(): continue` check since it's now handled in the thread.

**Step 4: Run test**

Run: `cd backend && python -m pytest tests/services/test_scanner_async.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/grimoire/services/scanner.py backend/tests/
git commit -m "perf: run file hash and directory walk in thread pool to unblock event loop"
```

---

## Summary & Execution Order

| Task | Priority | Impact | Effort |
|------|----------|--------|--------|
| 1. Thread pool for blocking handlers | CRITICAL | Unblocks event loop during processing | Medium |
| 2. Concurrent queue worker with semaphore | HIGH | 3-5x throughput increase | Medium |
| 3. Fix task priority order | HIGH | Covers appear immediately in UI | Small |
| 4. Batch queue insertion | MEDIUM | Fewer SQLite transactions during scan | Small |
| 5. SSE event bus (backend) | MEDIUM | Foundation for real-time updates | Medium |
| 6. SSE frontend integration | MEDIUM | Instant UI updates, less polling | Small |
| 7. Cache settings lookups | LOW | Eliminate redundant DB queries | Small |
| 8. Queue stats breakdown | LOW | Better progress visibility | Small |
| 9. Non-blocking scanner I/O | MEDIUM | Unblock event loop during scan | Small |

**Recommended execution order:** 1 → 2 → 3 → 9 → 4 → 5 → 6 → 7 → 8

Tasks 1 and 2 are the highest-impact changes. Task 3 is a quick win. Tasks 5-6 are a paired feature. Tasks 7-8 are polish.

**Dependencies:**
- Task 2 depends on Task 1 (concurrent worker only safe after handlers are thread-safe)
- Task 6 depends on Task 5 (frontend SSE needs backend SSE endpoint)
- All other tasks are independent
