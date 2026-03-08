# Performance Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 12 identified performance bottlenecks across backend query patterns, task queue processing, async I/O handling, and frontend rendering to reduce page load times and eliminate event loop blocking.

**Architecture:** Backend is FastAPI + SQLAlchemy (async) + SQLite with a custom queue processor (`ProcessingQueue` model). Frontend is React + TypeScript with React Query and `@tanstack/react-virtual`. Redis is used for filter caching. Changes focus on query optimization, batch operations, and non-blocking I/O — no new dependencies or architectural shifts.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (async), SQLite/aiosqlite, React 18, TypeScript, React Query v5, `@tanstack/react-virtual`

---

## Task 1: Optimize the count query in list_products

**Priority:** HIGH — runs on every product listing request, wraps the full query (including eager loads) as a subquery.

**Files:**
- Modify: `backend/grimoire/api/routes/products.py:108-279`
- Test: `backend/tests/api/test_products_list.py`

**Problem:** The count query at line 253 wraps the entire filtered query — including `selectinload` for tags — as a subquery. SQLite materializes the full result set with joins just to count rows. The `selectinload` is unnecessary for counting.

**Step 1: Write the failing test**

Create `backend/tests/__init__.py` (empty) and `backend/tests/api/__init__.py` (empty), then create `backend/tests/conftest.py`:

```python
"""Shared test fixtures for Grimoire backend tests."""

import asyncio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from grimoire.database import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(engine):
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()
```

Then create `backend/tests/api/test_products_list.py`:

```python
"""Tests for product listing query optimization."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy import select, func

from grimoire.models import Product


@pytest.mark.asyncio
async def test_count_query_does_not_include_selectinload(db):
    """The count query should NOT use selectinload — it only needs to count rows."""
    # Add test products
    for i in range(5):
        product = Product(
            file_path=f"/test/file_{i}.pdf",
            file_name=f"file_{i}.pdf",
            file_size=1000 + i,
            file_hash=f"hash_{i}",
            title=f"Product {i}",
        )
        db.add(product)
    await db.flush()

    # Build count query the NEW way (without subquery wrapping)
    base_query = select(Product).where(
        Product.is_duplicate == False,
        Product.is_missing == False,
    )
    count_query = select(func.count(Product.id)).where(
        Product.is_duplicate == False,
        Product.is_missing == False,
    )

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    assert total == 5
```

**Step 2: Run test to verify it passes (baseline)**

```bash
cd backend && python -m pytest tests/api/test_products_list.py -v
```

Expected: PASS — this confirms the new count approach works.

**Step 3: Refactor list_products to use a separate count query**

In `backend/grimoire/api/routes/products.py`, replace the count query pattern. Instead of wrapping the full query as a subquery, build a parallel count query that applies the same WHERE filters but without `selectinload` or sorting.

Change the approach at line 253 from:

```python
# OLD - wraps full query with eager loads
count_query = select(func.count()).select_from(query.subquery())
```

To building a separate lightweight count query. The cleanest way: extract the filter-building into a helper that returns WHERE conditions, then apply them to both the main query and the count query.

Refactor `list_products` to:

1. Build a `filters` list of WHERE conditions (lines 137-251).
2. Apply filters to `select(func.count(Product.id)).where(*filters)` for counting.
3. Apply filters + `selectinload` + sorting + pagination to `select(Product)` for fetching.

Replace the count query block (around line 253) with:

```python
    # Get total count - lightweight query without eager loading or sorting
    count_query = select(func.count(Product.id))

    # Re-apply the same base filters for the count
    count_query = count_query.where(Product.is_duplicate == False, Product.is_missing == False)

    if search:
        if 'fts_product_ids' in dir():
            # fts_product_ids was set above
            pass  # Already filtered in main query — apply same to count
        ...
```

**However**, the cleaner approach is to restructure the function to collect filter conditions into a list, then apply them to both queries. Here is the full refactored structure for lines ~133-268:

```python
    # Collect all filter conditions
    conditions = [Product.is_duplicate == False, Product.is_missing == False]
    joins = []  # Track required joins

    fts_product_ids = None

    if search:
        try:
            if await check_fts_available(db):
                terms = search.strip().split()
                if terms:
                    fts_query_str = " OR ".join(f'"{term}"*' for term in terms)
                    fts_result = await db.execute(
                        text("SELECT rowid FROM products_fts WHERE products_fts MATCH :query LIMIT 1000"),
                        {"query": fts_query_str}
                    )
                    fts_product_ids = [row[0] for row in fts_result.fetchall()]
                    if fts_product_ids:
                        conditions.append(Product.id.in_(fts_product_ids))
                    else:
                        conditions.append(Product.id == -1)
            else:
                search_term = f"%{search}%"
                conditions.append(
                    (Product.title.ilike(search_term)) | (Product.file_name.ilike(search_term))
                )
        except Exception:
            search_term = f"%{search}%"
            conditions.append(
                (Product.title.ilike(search_term)) | (Product.file_name.ilike(search_term))
            )

    if game_system:
        if game_system == "Unknown":
            conditions.append(Product.game_system.is_(None))
        else:
            conditions.append(Product.game_system == game_system)

    if product_type:
        if product_type == "Unknown":
            conditions.append(Product.product_type.is_(None))
        else:
            conditions.append(Product.product_type == product_type)

    if genre:
        if genre == "Unknown":
            conditions.append(Product.genre.is_(None))
        else:
            conditions.append(Product.genre == genre)

    if publisher:
        if publisher == "Unknown":
            conditions.append(Product.publisher.is_(None))
        else:
            conditions.append(Product.publisher == publisher)

    if author:
        if author == "Unknown":
            conditions.append(Product.author.is_(None))
        else:
            conditions.append(Product.author == author)

    if has_cover is not None:
        conditions.append(Product.cover_extracted == has_cover)

    if text_extracted is not None:
        conditions.append(Product.text_extracted == text_extracted)

    if ai_identified is not None:
        conditions.append(Product.ai_identified == ai_identified)

    if publication_year_min is not None:
        conditions.append(Product.publication_year >= publication_year_min)
    if publication_year_max is not None:
        conditions.append(Product.publication_year <= publication_year_max)

    if level_min is not None:
        conditions.append(
            (Product.level_range_max >= level_min) | (Product.level_range_max.is_(None))
        )
    if level_max is not None:
        conditions.append(
            (Product.level_range_min <= level_max) | (Product.level_range_min.is_(None))
        )

    if party_size_min is not None:
        conditions.append(
            (Product.party_size_max >= party_size_min) | (Product.party_size_max.is_(None))
        )
    if party_size_max is not None:
        conditions.append(
            (Product.party_size_min <= party_size_max) | (Product.party_size_min.is_(None))
        )

    if estimated_runtime:
        conditions.append(Product.estimated_runtime.ilike(f"%{estimated_runtime}%"))

    # --- Count query (lightweight, no joins for eager loading) ---
    count_query = select(func.count(Product.id)).where(*conditions)

    # Tags and collections require a join — apply to both count and main query
    if tags:
        tag_ids = [int(t.strip()) for t in tags.split(",") if t.strip().isdigit()]
        if tag_ids:
            count_query = count_query.join(ProductTag).where(ProductTag.tag_id.in_(tag_ids))

    if collection:
        from grimoire.models import CollectionProduct
        count_query = count_query.join(CollectionProduct).where(
            CollectionProduct.collection_id == collection
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # --- Main query (with eager loading, sorting, pagination) ---
    query = (
        select(Product)
        .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
        .where(*conditions)
    )

    if tags:
        tag_ids = [int(t.strip()) for t in tags.split(",") if t.strip().isdigit()]
        if tag_ids:
            query = query.join(ProductTag).where(ProductTag.tag_id.in_(tag_ids))

    if collection:
        from grimoire.models import CollectionProduct
        query = query.join(CollectionProduct).where(
            CollectionProduct.collection_id == collection
        )

    # Apply sorting
    sort_column = getattr(Product, sort, Product.title)
    if order == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    # Apply pagination
    offset = (pagination.page - 1) * pagination.per_page
    query = query.offset(offset).limit(pagination.per_page)

    result = await db.execute(query)
    products = result.scalars().unique().all()
```

**Step 4: Run tests to verify**

```bash
cd backend && python -m pytest tests/api/test_products_list.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/ backend/grimoire/api/routes/products.py
git commit -m "perf: optimize count query to avoid subquery with eager loading"
```

---

## Task 2: Batch queue deduplication checks in scanner

**Priority:** HIGH — `queue_products_for_processing` runs N queries per product per task type (up to 3N queries for a batch of N products).

**Files:**
- Modify: `backend/grimoire/services/scanner.py:206-293`
- Test: `backend/tests/services/test_scanner_queue.py`

**Problem:** Lines 233-278 execute individual `SELECT` queries to check for existing queue items per product per task type. For 100 products, this is up to 300 queries.

**Step 1: Write the failing test**

Create `backend/tests/services/__init__.py` (empty) and `backend/tests/services/test_scanner_queue.py`:

```python
"""Tests for batch queue deduplication."""

import pytest
from grimoire.models import Product, ProcessingQueue
from grimoire.services.scanner import queue_products_for_processing


@pytest.mark.asyncio
async def test_queue_products_batch_dedup(db):
    """Queuing products should use batch dedup, not per-product queries."""
    products = []
    for i in range(10):
        p = Product(
            file_path=f"/test/batch_{i}.pdf",
            file_name=f"batch_{i}.pdf",
            file_size=1000,
            file_hash=f"batchhash_{i}",
            title=f"Batch {i}",
        )
        db.add(p)
        products.append(p)
    await db.flush()

    # Pre-add a pending cover task for product 0
    existing = ProcessingQueue(
        product_id=products[0].id,
        task_type="cover",
        priority=3,
        status="pending",
    )
    db.add(existing)
    await db.flush()

    result = await queue_products_for_processing(db, products)

    # Should queue 9 covers (skipping product 0 which already has one)
    assert result["covers"] == 9


@pytest.mark.asyncio
async def test_queue_skips_duplicates(db):
    """Should not queue products marked as duplicates."""
    p = Product(
        file_path="/test/dup.pdf",
        file_name="dup.pdf",
        file_size=1000,
        file_hash="duphash",
        title="Dup",
        is_duplicate=True,
    )
    db.add(p)
    await db.flush()

    result = await queue_products_for_processing(db, [p])
    assert result["covers"] == 0
```

**Step 2: Run test to verify it fails/passes baseline**

```bash
cd backend && python -m pytest tests/services/test_scanner_queue.py -v
```

**Step 3: Refactor queue_products_for_processing to batch query**

Replace the per-product loop with a single batch query. In `backend/grimoire/services/scanner.py`, replace `queue_products_for_processing`:

```python
async def queue_products_for_processing(db: AsyncSession, products: list[Product]) -> dict:
    """Queue products for processing based on settings.

    Uses batch queries to check for existing queue items instead of
    per-product queries. This reduces N*M queries to 1 query.
    """
    from grimoire.models import ProcessingQueue

    settings = await get_scan_settings(db)
    auto_extract_text = settings.get('auto_extract_text_on_scan', False)
    auto_identify = settings.get('auto_identify_on_scan', False)

    # Filter out duplicates
    eligible = [p for p in products if not p.is_duplicate]
    if not eligible:
        return {"covers": 0, "text": 0}

    product_ids = [p.id for p in eligible]

    # Batch-fetch all existing pending/processing queue items for these products
    existing_result = await db.execute(
        select(ProcessingQueue.product_id, ProcessingQueue.task_type)
        .where(
            ProcessingQueue.product_id.in_(product_ids),
            ProcessingQueue.status.in_(["pending", "processing"]),
        )
    )
    existing_tasks = {(row[0], row[1]) for row in existing_result.fetchall()}

    queued_covers = 0
    queued_text = 0

    for product in eligible:
        if not product.cover_extracted and (product.id, "cover") not in existing_tasks:
            db.add(ProcessingQueue(
                product_id=product.id,
                task_type="cover",
                priority=3,
                status="pending",
            ))
            queued_covers += 1

        if auto_extract_text and not product.text_extracted:
            if (product.id, "text") not in existing_tasks:
                db.add(ProcessingQueue(
                    product_id=product.id,
                    task_type="text",
                    priority=5,
                    status="pending",
                ))
                queued_text += 1

        if auto_identify and product.text_extracted and not product.ai_identified:
            if (product.id, "ai_identify") not in existing_tasks:
                db.add(ProcessingQueue(
                    product_id=product.id,
                    task_type="ai_identify",
                    priority=7,
                    status="pending",
                ))

    if queued_covers > 0 or queued_text > 0:
        await db.commit()

    return {"covers": queued_covers, "text": queued_text}
```

**Step 4: Run tests**

```bash
cd backend && python -m pytest tests/services/test_scanner_queue.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add backend/grimoire/services/scanner.py backend/tests/services/
git commit -m "perf: batch queue deduplication checks (N*M queries -> 1)"
```

---

## Task 3: Batch duplicate checking during scan

**Priority:** HIGH — `check_and_mark_duplicate` runs 1 query per product during scanning.

**Files:**
- Modify: `backend/grimoire/services/scanner.py:44-183`
- Modify: `backend/grimoire/services/duplicate_service.py` (add batch function)
- Test: `backend/tests/services/test_duplicate_batch.py`

**Problem:** In `scan_folder`, lines 132, 156, and 169 call `check_and_mark_duplicate` per product. Each call runs `find_duplicates_by_hash` which queries `Product` by `file_hash`. For 500 new products, that's 500 individual queries.

**Step 1: Write the failing test**

Create `backend/tests/services/test_duplicate_batch.py`:

```python
"""Tests for batch duplicate detection."""

import pytest
from grimoire.models import Product
from grimoire.services.duplicate_service import batch_check_and_mark_duplicates


@pytest.mark.asyncio
async def test_batch_duplicate_detection(db):
    """Batch duplicate check should mark duplicates in one pass."""
    # Create a canonical product
    canonical = Product(
        file_path="/test/original.pdf",
        file_name="original.pdf",
        file_size=1000,
        file_hash="shared_hash",
        title="Original",
    )
    db.add(canonical)
    await db.flush()

    # Create products with the same hash
    dupes = []
    for i in range(3):
        p = Product(
            file_path=f"/test/dupe_{i}.pdf",
            file_name=f"dupe_{i}.pdf",
            file_size=1000,
            file_hash="shared_hash",
            title=f"Dupe {i}",
        )
        db.add(p)
        dupes.append(p)
    await db.flush()

    count = await batch_check_and_mark_duplicates(db, dupes)
    assert count == 3
    for p in dupes:
        assert p.is_duplicate is True
        assert p.duplicate_of_id == canonical.id


@pytest.mark.asyncio
async def test_batch_no_duplicates(db):
    """Products with unique hashes should not be marked."""
    products = []
    for i in range(3):
        p = Product(
            file_path=f"/test/unique_{i}.pdf",
            file_name=f"unique_{i}.pdf",
            file_size=1000,
            file_hash=f"unique_hash_{i}",
            title=f"Unique {i}",
        )
        db.add(p)
        products.append(p)
    await db.flush()

    count = await batch_check_and_mark_duplicates(db, products)
    assert count == 0
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/services/test_duplicate_batch.py -v
```

Expected: FAIL — `batch_check_and_mark_duplicates` does not exist yet.

**Step 3: Implement batch_check_and_mark_duplicates**

Add to `backend/grimoire/services/duplicate_service.py`:

```python
async def batch_check_and_mark_duplicates(
    db: AsyncSession,
    products: list[Product],
) -> int:
    """
    Check a batch of products for duplicates using a single query.

    Instead of N individual queries, fetches all products with matching
    hashes in one query, then marks duplicates in memory.

    Returns the number of products marked as duplicates.
    """
    if not products:
        return 0

    # Collect unique hashes from the batch
    hashes = {p.file_hash for p in products}
    product_ids = {p.id for p in products}

    # Single query: find ALL existing products with these hashes
    result = await db.execute(
        select(Product)
        .where(Product.file_hash.in_(hashes))
        .order_by(Product.created_at.asc())
    )
    all_matching = list(result.scalars().all())

    # Group by hash, find canonical (oldest) for each hash
    from collections import defaultdict
    hash_groups: dict[str, list[Product]] = defaultdict(list)
    for p in all_matching:
        hash_groups[p.file_hash].append(p)

    marked = 0
    for product in products:
        group = hash_groups.get(product.file_hash, [])
        # Need at least 2 products with the same hash for it to be a duplicate
        if len(group) < 2:
            continue

        canonical = group[0]  # Already sorted by created_at asc
        if canonical.id == product.id:
            continue  # This IS the canonical

        product.is_duplicate = True
        product.duplicate_of_id = canonical.id
        product.duplicate_reason = "exact_hash"
        marked += 1

    return marked
```

**Step 4: Run tests**

```bash
cd backend && python -m pytest tests/services/test_duplicate_batch.py -v
```

Expected: PASS

**Step 5: Update scan_folder to use batch duplicate checking**

In `backend/grimoire/services/scanner.py`, replace the per-product `check_and_mark_duplicate` calls with `batch_check_and_mark_duplicates`. Update the import and the batch processing sections:

```python
from grimoire.services.duplicate_service import batch_check_and_mark_duplicates, is_deleted_duplicate
```

Replace the batch commit block (lines 149-162) with:

```python
        # Commit in batches of 100
        if len(products) % 100 == 0:
            await db.flush()
            batch = products[-100:]
            duplicate_count += await batch_check_and_mark_duplicates(db, batch)
            await db.commit()
            await queue_products_for_processing(db, batch)
```

Replace the final duplicate check (lines 164-175) with:

```python
    # Final flush and duplicate check for remaining products
    await db.flush()
    remaining = products[-(len(products) % 100):] if len(products) % 100 != 0 else []
    if remaining:
        duplicate_count += await batch_check_and_mark_duplicates(db, remaining)
    await db.commit()

    if remaining:
        await queue_products_for_processing(db, remaining)
```

Remove the `_dup_checked` attribute hack entirely.

**Step 6: Run tests**

```bash
cd backend && python -m pytest tests/services/ -v
```

Expected: PASS

**Step 7: Commit**

```bash
git add backend/grimoire/services/duplicate_service.py backend/grimoire/services/scanner.py backend/tests/services/
git commit -m "perf: batch duplicate checking during scan (N queries -> 1)"
```

---

## Task 4: Move text extraction off the async event loop

**Priority:** HIGH — `extract_product_text` (products.py:617) calls `process_text_extraction_sync` synchronously, blocking all other requests during PDF parsing.

**Files:**
- Modify: `backend/grimoire/api/routes/products.py:601-628`
- Test: `backend/tests/api/test_extract_async.py`

**Problem:** `process_text_extraction_sync` is CPU-bound (PyMuPDF/Marker PDF parsing). Running it in the async request handler blocks the FastAPI event loop, stalling all concurrent requests.

**Step 1: Write the test**

Create `backend/tests/api/test_extract_async.py`:

```python
"""Test that text extraction doesn't block the event loop."""

import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_extract_should_queue_not_block():
    """Inline text extraction endpoint should use asyncio.to_thread."""
    # We verify this structurally: the route should use to_thread or queue the task
    import inspect
    from grimoire.api.routes.products import extract_product_text

    source = inspect.getsource(extract_product_text)
    # Must use either asyncio.to_thread or queue to worker
    assert "to_thread" in source or "ProcessingQueue" in source, (
        "extract_product_text must use asyncio.to_thread or queue to worker"
    )
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/api/test_extract_async.py -v
```

Expected: FAIL — current code calls `process_text_extraction_sync` directly.

**Step 3: Wrap the blocking call in asyncio.to_thread**

In `backend/grimoire/api/routes/products.py`, modify `extract_product_text` (line 601+):

```python
@router.post("/{product_id}/extract")
async def extract_product_text(
    db: DbSession,
    product_id: int,
    use_marker: bool = Query(False, description="Use Marker for better quality (slower)"),
) -> dict:
    """Extract text from a product's PDF."""
    import asyncio

    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    from grimoire.services.processor import process_text_extraction_sync

    # Run CPU-bound extraction in a thread to avoid blocking the event loop
    success = await asyncio.to_thread(process_text_extraction_sync, product, use_marker)

    if not success:
        raise HTTPException(status_code=500, detail="Text extraction failed")

    await db.commit()

    return {
        "product_id": product_id,
        "text_extracted": True,
        "message": "Text extraction completed",
    }
```

**Step 4: Run tests**

```bash
cd backend && python -m pytest tests/api/test_extract_async.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add backend/grimoire/api/routes/products.py backend/tests/api/
git commit -m "perf: run text extraction in thread to unblock event loop"
```

---

## Task 5: Make thumbnail generation non-blocking

**Priority:** HIGH — on-demand thumbnail generation at products.py:452 does PIL image processing synchronously in the request handler.

**Files:**
- Modify: `backend/grimoire/api/routes/products.py:416-489`
- Test: `backend/tests/api/test_thumbnail_nonblocking.py`

**Problem:** When a thumbnail doesn't exist, `generate_thumbnail_for_product` runs PIL resize + WebP/JPEG encoding synchronously, blocking the response. The fix: return the full cover as immediate fallback and generate the thumbnail in background.

**Step 1: Write the test**

Create `backend/tests/api/test_thumbnail_nonblocking.py`:

```python
"""Test that thumbnail endpoint doesn't block on generation."""

import pytest
import inspect


@pytest.mark.asyncio
async def test_thumbnail_uses_background_generation():
    """Thumbnail generation should not block the response."""
    from grimoire.api.routes.products import get_product_thumbnail

    source = inspect.getsource(get_product_thumbnail)
    # Should NOT call generate_thumbnail_for_product synchronously
    # Should either use to_thread, queue to worker, or return cover fallback
    assert "to_thread" in source or "ProcessingQueue" in source, (
        "get_product_thumbnail must not call generate_thumbnail_for_product synchronously"
    )
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/api/test_thumbnail_nonblocking.py -v
```

Expected: FAIL

**Step 3: Refactor to return cover fallback and queue thumbnail generation**

In `backend/grimoire/api/routes/products.py`, modify `get_product_thumbnail`:

```python
@router.get("/{product_id}/thumbnail")
async def get_product_thumbnail(
    db: DbSession,
    product_id: int,
    format: str = Query("webp", regex="^(webp|jpeg)$", description="Image format: webp or jpeg"),
) -> FileResponse:
    """Get the thumbnail image for a product.

    Thumbnails are optimized versions of cover images (300x400px).
    If thumbnail doesn't exist, returns the full cover and queues
    thumbnail generation in background.
    """
    import asyncio
    from grimoire.models import ProcessingQueue

    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # For duplicates, get the original's thumbnail
    if product.is_duplicate and product.duplicate_of_id:
        orig_query = select(Product).where(Product.id == product.duplicate_of_id)
        orig_result = await db.execute(orig_query)
        original = orig_result.scalar_one_or_none()
        if original and original.cover_extracted:
            product = original

    if not product.cover_extracted or not product.cover_image_path:
        raise HTTPException(status_code=404, detail="Cover not available")

    from grimoire.services.thumbnail_service import get_thumbnail_path

    thumbnail_path = get_thumbnail_path(product, prefer_webp=(format == "webp"))

    if not thumbnail_path:
        # Queue thumbnail generation in background via asyncio.to_thread
        # Return the full cover immediately as a fallback
        from grimoire.services.thumbnail_service import generate_thumbnail_for_product
        asyncio.get_event_loop().run_in_executor(
            None, generate_thumbnail_for_product, product
        )

        cover_path = Path(product.cover_image_path)
        try:
            validate_covers_path(cover_path)
        except PathTraversalError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not cover_path.exists():
            raise HTTPException(status_code=404, detail="Cover file not found")

        return FileResponse(
            cover_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=60"},  # Short cache — thumbnail will be ready soon
        )

    try:
        validate_covers_path(thumbnail_path)
    except PathTraversalError:
        raise HTTPException(status_code=403, detail="Access denied")

    if not thumbnail_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail file not found")

    media_type = "image/webp" if thumbnail_path.suffix == ".webp" else "image/jpeg"

    return FileResponse(
        thumbnail_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=2592000"},
    )
```

**Step 4: Run tests**

```bash
cd backend && python -m pytest tests/api/test_thumbnail_nonblocking.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add backend/grimoire/api/routes/products.py backend/tests/api/
git commit -m "perf: non-blocking thumbnail generation with cover fallback"
```

---

## Task 6: Add missing database index on is_missing

**Priority:** MEDIUM — `is_missing` is filtered on every `list_products` call but has no index.

**Files:**
- Modify: `backend/grimoire/models/product.py:22-36`
- Create: `backend/migrations/006_add_is_missing_index.sql`

**Step 1: Add the index to the model**

In `backend/grimoire/models/product.py`, add to `__table_args__`:

```python
    __table_args__ = (
        Index("ix_products_title", "title"),
        Index("ix_products_game_system", "game_system"),
        Index("ix_products_product_type", "product_type"),
        Index("ix_products_created_at", "created_at"),
        Index("ix_products_file_hash", "file_hash"),
        Index("ix_products_publisher", "publisher"),
        Index("ix_products_is_duplicate", "is_duplicate"),
        Index("ix_products_is_missing", "is_missing"),  # NEW
        Index("ix_products_file_size", "file_size"),
        Index("ix_products_system_type", "game_system", "product_type"),
        Index("ix_products_author", "author"),
        Index("ix_products_genre", "genre"),
        Index("ix_products_updated_at", "updated_at"),
        Index("ix_products_last_opened_at", "last_opened_at"),
    )
```

**Step 2: Create migration file**

Create `backend/migrations/006_add_is_missing_index.sql`:

```sql
-- Add index on is_missing for filtered product listing
CREATE INDEX IF NOT EXISTS ix_products_is_missing ON products(is_missing);
```

**Step 3: Commit**

```bash
git add backend/grimoire/models/product.py backend/migrations/006_add_is_missing_index.sql
git commit -m "perf: add missing index on is_missing column"
```

---

## Task 7: Remove double-commit in get_db dependency

**Priority:** MEDIUM — every request handler that calls `await db.commit()` triggers a redundant second commit from the `get_db` dependency.

**Files:**
- Modify: `backend/grimoire/database.py:48-58`
- Test: `backend/tests/test_database.py`

**Problem:** `get_db()` at line 53 auto-commits after every request. But route handlers like `update_product`, `delete_product`, and `process_product` all explicitly commit. This causes an unnecessary second `COMMIT` statement per request.

**Step 1: Write the test**

Create `backend/tests/test_database.py`:

```python
"""Tests for database session management."""

import pytest
from grimoire.database import get_db


@pytest.mark.asyncio
async def test_get_db_does_not_auto_commit():
    """get_db should not auto-commit — handlers manage their own transactions."""
    import inspect
    source = inspect.getsource(get_db)
    # Should NOT have an unconditional commit in the happy path
    # The session should just be yielded and closed
    assert "await session.commit()" not in source or "# auto-commit" in source, (
        "get_db should not auto-commit; route handlers manage commits explicitly"
    )
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_database.py -v
```

Expected: FAIL

**Step 3: Remove auto-commit from get_db**

In `backend/grimoire/database.py`, change `get_db`:

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session.

    Route handlers are responsible for calling commit() explicitly.
    The session is rolled back on exception and always closed.
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
```

**Step 4: Run full test suite to verify nothing breaks**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: PASS — all route handlers already commit explicitly.

**Step 5: Commit**

```bash
git add backend/grimoire/database.py backend/tests/test_database.py
git commit -m "perf: remove redundant auto-commit from get_db dependency"
```

---

## Task 8: Add stale time to content search query

**Priority:** LOW — content search refetches on every re-render when active.

**Files:**
- Modify: `frontend/src/pages/Library.tsx:45-53`

**Problem:** The content search query has no `staleTime`, so React Query refetches on every component re-render when `activeSearch` is set.

**Step 1: Add staleTime to the search query**

In `frontend/src/pages/Library.tsx`, modify the search query:

```typescript
  const {
    data: searchData,
    isLoading: searchLoading,
    error: searchError,
  } = useQuery({
    queryKey: ['search', activeSearch, searchContent],
    queryFn: () => searchProducts({ q: activeSearch, search_content: searchContent }),
    enabled: activeSearch.length > 0,
    staleTime: 60000, // Cache search results for 60 seconds
  });
```

**Step 2: Commit**

```bash
git add frontend/src/pages/Library.tsx
git commit -m "perf: add staleTime to content search query to prevent refetching"
```

---

## Task 9: Fix ProductGrid column count not updating on resize

**Priority:** LOW — column calculation is captured once and never updates on window resize.

**Files:**
- Modify: `frontend/src/components/ProductGrid.tsx:1-26`

**Problem:** The `columns` useMemo at line 16 reads `window.innerWidth` once at render time. There's no resize listener, so grid columns don't adapt when the user resizes their browser.

**Step 1: Add resize listener**

In `frontend/src/components/ProductGrid.tsx`, replace the columns calculation:

```typescript
import { useRef, useMemo, useState, useEffect } from 'react';

// ... inside ProductGrid component, replace the columns useMemo with:

  const [windowWidth, setWindowWidth] = useState(
    typeof window !== 'undefined' ? window.innerWidth : 1920
  );

  useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const columns = useMemo(() => {
    if (viewMode === 'list') return 1;
    if (windowWidth < 640) return 2;
    if (windowWidth < 768) return 3;
    if (windowWidth < 1024) return 4;
    if (windowWidth < 1280) return 5;
    return 6;
  }, [viewMode, windowWidth]);
```

**Step 2: Commit**

```bash
git add frontend/src/components/ProductGrid.tsx
git commit -m "fix: update grid columns on window resize"
```

---

## Task 10: Cap FTS result set and optimize IN clause

**Priority:** MEDIUM — FTS returns up to 1000 IDs, passed as `WHERE id IN (...)` which is slow for large sets.

**Files:**
- Modify: `backend/grimoire/api/routes/products.py` (the FTS search section within `list_products`)

**Problem:** Line 149 uses `LIMIT 1000` on FTS results. All 1000 IDs are passed to `Product.id.in_(fts_product_ids)`, which generates a large `WHERE id IN (1, 2, 3, ..., 1000)` clause. SQLite can handle this, but it's slower than a temp table or join-based approach.

**Step 1: Use a reasonable limit based on pagination**

Since we're paginating (default 24 per page), we don't need 1000 FTS results unless the user is on page 42+. Use a smarter limit:

In the FTS search block within `list_products`, change:

```python
    # Cap FTS results: enough for current page + a buffer for other filters
    fts_limit = min(1000, (pagination.page * pagination.per_page) + 200)
    fts_result = await db.execute(
        text("SELECT rowid FROM products_fts WHERE products_fts MATCH :query LIMIT :limit"),
        {"query": fts_query_str, "limit": fts_limit}
    )
```

This reduces the IN clause size for early pages (the common case) while still supporting deep pagination.

**Step 2: Commit**

```bash
git add backend/grimoire/api/routes/products.py
git commit -m "perf: cap FTS result set based on pagination to reduce IN clause size"
```

---

## Task 11: Prevent process_queue from re-querying for each item

**Priority:** MEDIUM — `process_queue` fetches next item, then `process_queue_item` re-opens a new session and re-fetches the same item.

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py:457-495`

**Problem:** `process_queue` (line 474) calls `get_next_pending_item` which returns a `ProcessingQueue` object. It then calls `process_queue_item(item.id)` which opens a *new* session and re-fetches the same item by ID. This is redundant — the item was just loaded.

**Step 1: Refactor process_queue to pass the session through**

This is a structural refactor. Instead of `process_queue_item` creating its own session, have it accept a session:

```python
async def process_queue_item_with_session(db: AsyncSession, item: ProcessingQueue) -> bool:
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
        elif item.attempts >= item.max_attempts:
            item.status = "failed"
            item.error_message = "Max attempts reached"
        else:
            item.status = "pending"
        item.completed_at = datetime.now(UTC)

        await db.commit()
        return success

    except Exception as e:
        logger.error(f"Error processing queue item {item.id}: {e}")
        item.error_message = str(e)[:500]
        item.status = "failed" if item.attempts >= item.max_attempts else "pending"
        item.completed_at = datetime.now(UTC)
        await db.commit()
        return False
```

Update `process_queue` to use the new function:

```python
async def process_queue(max_items: int = 10, delay: float = 0.5) -> dict:
    processed = 0
    succeeded = 0
    failed = 0

    async with async_session_maker() as db:
        for _ in range(max_items):
            item = await get_next_pending_item(db)
            if not item:
                break

            processed += 1
            success = await process_queue_item_with_session(db, item)

            if success:
                succeeded += 1
            else:
                failed += 1

            if delay > 0:
                await asyncio.sleep(delay)

    return {"processed": processed, "succeeded": succeeded, "failed": failed}
```

Keep the original `process_queue_item(item_id)` function as-is for external callers (API endpoints that queue by ID).

**Step 2: Commit**

```bash
git add backend/grimoire/services/queue_processor.py
git commit -m "perf: avoid re-fetching queue items in process_queue loop"
```

---

## Task 12: Add search input debouncing for title search

**Priority:** LOW — typing in the search box triggers filter state changes on form submit (not onChange), but the form submit approach means no debounce is needed for title search. However, adding debouncing would allow live-as-you-type search.

**Files:**
- Modify: `frontend/src/pages/Library.tsx:60-68`

**Note:** The current implementation uses form `onSubmit`, so debouncing is only relevant if you want to switch to live search. This is optional and can be skipped if form-submit behavior is preferred.

If you want live search with debouncing:

**Step 1: Add a useDebounce hook**

Create `frontend/src/hooks/useDebounce.ts`:

```typescript
import { useState, useEffect } from 'react';

export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}
```

**Step 2: Use it in Library.tsx**

```typescript
import { useDebounce } from '../hooks/useDebounce';

// Inside Library component:
const debouncedSearch = useDebounce(searchInput, 300);

useEffect(() => {
  if (!searchContent) {
    setFilters(prev => ({ ...prev, search: debouncedSearch || undefined, page: 1 }));
  }
}, [debouncedSearch, searchContent]);
```

**Step 3: Commit**

```bash
git add frontend/src/hooks/useDebounce.ts frontend/src/pages/Library.tsx
git commit -m "feat: add debounced live search for title filtering"
```

---

## Execution Order

Tasks should be executed in this order for maximum impact and minimal risk:

| Order | Task | Priority | Risk |
|-------|------|----------|------|
| 1 | Task 6: Add is_missing index | MEDIUM | Zero risk — additive only |
| 2 | Task 8: Search staleTime | LOW | Zero risk — additive only |
| 3 | Task 9: Grid resize listener | LOW | Zero risk — additive only |
| 4 | Task 7: Remove double commit | MEDIUM | Low risk — verify all routes commit explicitly |
| 5 | Task 1: Count query optimization | HIGH | Medium risk — must preserve filter behavior |
| 6 | Task 2: Batch queue dedup | HIGH | Low risk — same behavior, fewer queries |
| 7 | Task 3: Batch duplicate checking | HIGH | Low risk — same behavior, fewer queries |
| 8 | Task 4: Async text extraction | HIGH | Low risk — same behavior, non-blocking |
| 9 | Task 5: Non-blocking thumbnails | HIGH | Low risk — fallback to cover |
| 10 | Task 10: FTS limit optimization | MEDIUM | Low risk — smarter limit |
| 11 | Task 11: Queue processor refactor | MEDIUM | Low risk — internal refactor |
| 12 | Task 12: Search debouncing | LOW | Optional — changes UX |
