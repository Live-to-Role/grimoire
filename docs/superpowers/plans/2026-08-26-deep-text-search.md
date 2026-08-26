# Deep Text Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the whole of every document searchable by keyword, replacing the 50,000-character truncation that currently hides 71% of the library's text.

**Architecture:** A standalone FTS5 table, `product_chunks_fts`, indexes the chunk text that `product_embeddings` already stores for every document, uncapped and carrying page numbers. `products_fts` reverts to metadata only. The chunk index is written by the same task that writes chunks — not by a trigger — and orphans are swept rather than hooked per delete site.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x (async), SQLite FTS5, pytest + pytest-asyncio (`asyncio_mode = "auto"`).

**Spec:** `docs/superpowers/specs/2026-08-26-deep-text-search-design.md`

## Global Constraints

- Test runner is the **miniconda** interpreter: `C:/Users/mkemi/miniconda3/python.exe -m pytest`, run from `backend/`. Do **not** use `backend/.venv` — it has no pytest.
- Re-measure the test baseline before starting. As of 2026-08-26 it is **620 passed, 1 failed**; the failure is `tests/api/test_browse.py::test_browse_falls_back_when_home_is_unavailable`, pre-existing and unrelated. A change is clean if it adds no new failures.
- **The unary `+` on boolean filters in FTS queries is load-bearing.** Without it SQLite drives the join from `ix_products_is_duplicate` and re-runs the MATCH once per product: ~87 s per query instead of ~0.03 s. Every new FTS query must carry it. See `fts_service.py:62`.
- SQLite foreign-key enforcement is **off** in this application, so `ondelete="CASCADE"` never fires. Deletion is done by ORM `delete-orphan` relationships. A virtual table has no ORM relationship, so it cannot rely on either.
- Route handlers commit explicitly; `get_db()` does not auto-commit.
- The app deliberately starts **paused**. Resume with `POST /api/v1/queue/resume` before expecting queued work to run.
- Chunk text is capped at 500 characters per chunk with overlap; `chunk[:1000]` in `handle_embed_task` never actually truncates. Verified: 0 of 300,000 sampled chunks reach 1,000 chars, max is 500.

---

### Task 1: Record the baseline

Nothing can be claimed later without this. The eval numbers have drifted twice before, so historical figures in memory or older docs must not be reused.

**Files:**
- Create: `backend/runs/deep-text-baseline.json`

**Interfaces:**
- Consumes: nothing.
- Produces: `backend/runs/deep-text-baseline.json`, the `--compare` target for Task 9.

- [ ] **Step 1: Confirm Ollama is up**

The eval embeds each query, so it needs Ollama running.

Run: `curl -s -m 5 http://localhost:11434/api/tags`
Expected: a JSON body listing models. If this fails, start Ollama before continuing.

- [ ] **Step 2: Record the search-quality baseline**

Run from `backend/`:

```bash
C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py --save runs/deep-text-baseline.json
```

Expected: completes in roughly 70 seconds and prints hit@k and MRR. Write the printed numbers into the task notes — they are the bar Task 9 must not regress.

- [ ] **Step 3: Record the query-latency baseline**

```bash
C:/Users/mkemi/miniconda3/python.exe -c "
import asyncio, time, sys
sys.path.insert(0, '.')
from grimoire.database import async_session_maker
from grimoire.services.fts_service import fts_candidates

async def main():
    async with async_session_maker() as db:
        for q in ['dungeon', 'Kurabanda', 'wizard spell cards']:
            t = time.perf_counter()
            rows = await fts_candidates(db, q, limit=150)
            print('%-20s %5.3fs  %d hits' % (q, time.perf_counter() - t, len(rows)))
asyncio.run(main())
"
```

Expected: each query well under a second. Record the numbers. If any query takes tens of seconds, the `+` regression is already present and must be investigated before proceeding.

- [ ] **Step 4: Record the database size**

Run: `ls -l backend/data/grimoire.db`
Record the byte count. Task 5 compares against it to extrapolate index growth.

- [ ] **Step 5: Commit**

```bash
git add backend/runs/deep-text-baseline.json
git commit -m "test(search): record deep-text-search baseline before indexing changes"
```

---

### Task 2: Create the chunk index table

**Files:**
- Modify: `backend/grimoire/database.py` (inside `_ensure_fts_table`, after the `products_fts` creation block and before the trigger definitions)
- Test: `backend/tests/services/test_chunk_fts_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces: table `product_chunks_fts` with columns `chunk_text, product_id, chunk_index, page_start, page_end`, created by `_ensure_fts_table(conn)`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_chunk_fts_schema.py`:

```python
"""The body index is a separate table from the metadata index.

products_fts is metadata-only and trigger-maintained. The body has a different
owner, a different lifecycle, and one row per chunk rather than one per
product, so it gets its own table.
"""
from sqlalchemy import text

from grimoire.database import _ensure_fts_table


async def _columns(db, table: str) -> list[str]:
    rows = (await db.execute(text(f"PRAGMA table_info({table})"))).all()
    return [r[1] for r in rows]


async def test_ensure_fts_table_creates_the_chunk_index(db):
    await _ensure_fts_table(await db.connection())

    assert await _columns(db, "product_chunks_fts") == [
        "chunk_text", "product_id", "chunk_index", "page_start", "page_end",
    ]


async def test_ensure_fts_table_is_idempotent(db):
    """It runs on every startup; a second call must not throw or wipe rows."""
    conn = await db.connection()
    await _ensure_fts_table(conn)
    await db.execute(text(
        "INSERT INTO product_chunks_fts(rowid, chunk_text, product_id, chunk_index,"
        " page_start, page_end) VALUES (1, 'kurabanda treetops', 7, 0, 32, 33)"
    ))

    await _ensure_fts_table(conn)

    rows = (await db.execute(text(
        "SELECT product_id FROM product_chunks_fts WHERE product_chunks_fts MATCH 'kurabanda'"
    ))).all()
    assert [r[0] for r in rows] == [7]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_chunk_fts_schema.py -v`
Expected: FAIL with `no such table: product_chunks_fts`.

- [ ] **Step 3: Add the table**

In `backend/grimoire/database.py`, inside `_ensure_fts_table`, immediately before the `CREATE TRIGGER IF NOT EXISTS products_fts_insert` block:

```python
    # The body index. Separate from products_fts because the two have
    # different owners: products_fts holds metadata maintained by triggers,
    # while the body is written by the task that produces chunks. Sharing one
    # table is what produced dc377a7, where the metadata trigger blanked the
    # body on every product update.
    #
    # UNINDEXED keeps the identifiers and page numbers out of the term index
    # while still returning them with the hit, so a match needs no join.
    await conn.execute(text("""
        CREATE VIRTUAL TABLE IF NOT EXISTS product_chunks_fts USING fts5(
            chunk_text,
            product_id UNINDEXED,
            chunk_index UNINDEXED,
            page_start UNINDEXED,
            page_end UNINDEXED
        )
    """))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_chunk_fts_schema.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the full suite**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest -q`
Expected: 622 passed, 1 failed (the pre-existing `test_browse` failure).

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/database.py backend/tests/services/test_chunk_fts_schema.py
git commit -m "feat(fts): add product_chunks_fts, a body index separate from metadata"
```

---

### Task 3: Write and clear the chunk index

**Files:**
- Modify: `backend/grimoire/services/fts_service.py` (add two functions at the end of the file)
- Test: `backend/tests/services/test_chunk_fts_write.py`

**Interfaces:**
- Consumes: `product_chunks_fts` (Task 2).
- Produces:
  - `async def clear_product_chunk_index(db: AsyncSession, product_id: int) -> None`
  - `async def index_product_chunks(db: AsyncSession, product_id: int) -> int` — returns rows written.

⚠️ **The FTS rowid is deliberately `ProductEmbedding.id`.** `product_id` is an
UNINDEXED column, so `DELETE ... WHERE product_id = ?` is a full scan of 3.3M
rows — unusable per product. Deleting by `rowid IN (SELECT id FROM
product_embeddings WHERE product_id = ?)` uses `ix_product_embeddings_product_id`
and then the FTS primary key.

⚠️ **This makes ordering load-bearing.** `clear_product_chunk_index` resolves
rowids through `product_embeddings`, so it must run **before** those rows are
deleted. Clearing after the embeddings are gone matches nothing and leaves
orphans. Task 4 depends on this ordering; Task 5 provides the sweep that
catches anything missed.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_chunk_fts_write.py`:

```python
"""Writing a product's chunks into the body index.

The index mirrors product_embeddings.chunk_text, which is the full document:
chunks cap at 500 characters and overlap, so nothing is truncated the way the
old 50,000-character products_fts body was.
"""
import pytest
from sqlalchemy import text

from grimoire.database import _ensure_fts_table
from grimoire.models import Product, ProductEmbedding
from grimoire.services.fts_service import (
    clear_product_chunk_index,
    index_product_chunks,
)


@pytest.fixture
async def chunked_product(db):
    await _ensure_fts_table(await db.connection())
    product = Product(
        file_path=r"D:\Games\sf1.pdf",
        file_name="sf1.pdf",
        file_size=1024,
        file_hash="sf1hash",
        title="SF1 Volturnus Planet of Mystery",
        text_extracted=True,
    )
    db.add(product)
    await db.flush()

    for i, (body, ps, pe) in enumerate([
        ("The party lands on Volturnus in a damaged shuttle.", 1, 2),
        ("The Kurabanda live in the treetops and fear the Sathar.", 32, 33),
        ("Alcazzar holds the robot foundry beneath the sand.", 35, 36),
    ]):
        emb = ProductEmbedding(
            product_id=product.id,
            chunk_index=i,
            chunk_text=body,
            embedding_model="test",
            embedding_dim=3,
            page_start=ps,
            page_end=pe,
        )
        emb.set_embedding_vector([0.1, 0.2, 0.3])
        db.add(emb)
    await db.commit()
    return product


async def _match(db, term: str) -> list[tuple]:
    rows = (await db.execute(text(
        "SELECT product_id, chunk_index, page_start, page_end"
        " FROM product_chunks_fts WHERE product_chunks_fts MATCH :q"
        " ORDER BY chunk_index"
    ), {"q": term})).all()
    return [tuple(r) for r in rows]


async def test_index_writes_one_row_per_chunk(db, chunked_product):
    written = await index_product_chunks(db, chunked_product.id)
    assert written == 3


async def test_a_term_deep_in_the_document_is_findable(db, chunked_product):
    """The whole point: page 32 is past where the old 50k cap would have cut."""
    await index_product_chunks(db, chunked_product.id)

    hits = await _match(db, "Kurabanda")
    assert hits == [(chunked_product.id, 1, 32, 33)]


async def test_page_numbers_come_back_with_the_hit(db, chunked_product):
    """UNINDEXED columns travel with the match, so no join is needed."""
    await index_product_chunks(db, chunked_product.id)

    (_, _, page_start, page_end), = await _match(db, "Alcazzar")
    assert (page_start, page_end) == (35, 36)


async def test_reindexing_replaces_rather_than_duplicates(db, chunked_product):
    await index_product_chunks(db, chunked_product.id)
    await clear_product_chunk_index(db, chunked_product.id)
    await index_product_chunks(db, chunked_product.id)

    assert len(await _match(db, "Kurabanda")) == 1


async def test_clear_removes_only_this_product(db, chunked_product):
    other = Product(
        file_path=r"D:\Games\other.pdf",
        file_name="other.pdf",
        file_size=1024,
        file_hash="otherhash",
        title="Other Book",
        text_extracted=True,
    )
    db.add(other)
    await db.flush()
    emb = ProductEmbedding(
        product_id=other.id,
        chunk_index=0,
        chunk_text="The Kurabanda appear here too.",
        embedding_model="test",
        embedding_dim=3,
        page_start=1,
        page_end=1,
    )
    emb.set_embedding_vector([0.1, 0.2, 0.3])
    db.add(emb)
    await db.commit()

    await index_product_chunks(db, chunked_product.id)
    await index_product_chunks(db, other.id)
    await clear_product_chunk_index(db, chunked_product.id)

    hits = await _match(db, "Kurabanda")
    assert [h[0] for h in hits] == [other.id]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_chunk_fts_write.py -v`
Expected: FAIL with `ImportError: cannot import name 'clear_product_chunk_index'`.

- [ ] **Step 3: Add the two functions**

Append to `backend/grimoire/services/fts_service.py`:

```python
async def clear_product_chunk_index(db: AsyncSession, product_id: int) -> None:
    """Remove a product's rows from the body index.

    ⚠️ Must run BEFORE the product's product_embeddings rows are deleted. The
    FTS rowid is the embedding id, so this resolves rowids through
    product_embeddings; once those rows are gone it matches nothing and leaves
    orphans behind. prune_orphaned_chunk_index() is the safety net.

    Deleting by rowid rather than by product_id is not a micro-optimisation:
    product_id is UNINDEXED, so filtering on it scans every row in a 3.3M-row
    table.
    """
    await db.execute(
        text("""
            DELETE FROM product_chunks_fts
            WHERE rowid IN (
                SELECT id FROM product_embeddings WHERE product_id = :product_id
            )
        """),
        {"product_id": product_id},
    )


async def index_product_chunks(db: AsyncSession, product_id: int) -> int:
    """Mirror a product's chunk text into the body index. Returns rows written.

    Deliberately not a database trigger. Trigger-maintained indexing is what
    produced dc377a7: the trigger drifted from the schema it served, blanked
    2,800 products' text, and went unnoticed for months because nothing
    errored. An explicit write path is testable.
    """
    rows = (await db.execute(
        select(
            ProductEmbedding.id,
            ProductEmbedding.chunk_index,
            ProductEmbedding.chunk_text,
            ProductEmbedding.page_start,
            ProductEmbedding.page_end,
        )
        .where(ProductEmbedding.product_id == product_id)
        .order_by(ProductEmbedding.chunk_index)
    )).all()

    for row_id, chunk_index, chunk_text, page_start, page_end in rows:
        await db.execute(
            text("""
                INSERT INTO product_chunks_fts(
                    rowid, chunk_text, product_id, chunk_index, page_start, page_end
                ) VALUES (:rowid, :chunk_text, :product_id, :chunk_index, :page_start, :page_end)
            """),
            {
                "rowid": row_id,
                "chunk_text": chunk_text,
                "product_id": product_id,
                "chunk_index": chunk_index,
                "page_start": page_start,
                "page_end": page_end,
            },
        )

    return len(rows)
```

Add the model import at the top of `fts_service.py`, beside the existing `Product` import:

```python
from grimoire.models import ProductEmbedding
```

If `select` is not already imported in this module, add it:

```python
from sqlalchemy import select
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_chunk_fts_write.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run the full suite**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest -q`
Expected: 627 passed, 1 failed (pre-existing).

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/services/fts_service.py backend/tests/services/test_chunk_fts_write.py
git commit -m "feat(fts): write and clear the chunk body index"
```

---

### Task 4: Keep the index in step with the chunks

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py` (`handle_embed_task`, around the `delete(ProductEmbedding)` call and the final `await db.commit()`)
- Test: `backend/tests/services/test_chunk_fts_sync.py`

**Interfaces:**
- Consumes: `clear_product_chunk_index`, `index_product_chunks` (Task 3).
- Produces: `handle_embed_task` leaves the body index consistent with `product_embeddings`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_chunk_fts_sync.py`:

```python
"""Re-embedding a product must leave the body index consistent.

handle_embed_task deletes every chunk and rewrites it. If the index is not
cleared first, the old rows survive as orphans and stale text stays findable
forever.
"""
import json

import pytest
from sqlalchemy import text

from grimoire.database import _ensure_fts_table
from grimoire.models import Product, ProductEmbedding
from grimoire.services.fts_service import clear_product_chunk_index, index_product_chunks


@pytest.fixture
async def product_with_index(db, tmp_path):
    await _ensure_fts_table(await db.connection())
    text_file = tmp_path / "extracted.json"
    text_file.write_text(json.dumps({"markdown": "placeholder"}), encoding="utf-8")

    product = Product(
        file_path=r"D:\Games\sf1.pdf",
        file_name="sf1.pdf",
        file_size=1024,
        file_hash="sf1hash",
        title="SF1 Volturnus",
        text_extracted=True,
        extracted_text_path=str(text_file),
    )
    db.add(product)
    await db.flush()

    emb = ProductEmbedding(
        product_id=product.id,
        chunk_index=0,
        chunk_text="The Kurabanda live in the treetops.",
        embedding_model="test",
        embedding_dim=3,
        page_start=32,
        page_end=33,
    )
    emb.set_embedding_vector([0.1, 0.2, 0.3])
    db.add(emb)
    await db.commit()
    await index_product_chunks(db, product.id)
    await db.commit()
    return product


async def _terms_findable(db, term: str) -> int:
    rows = (await db.execute(text(
        "SELECT rowid FROM product_chunks_fts WHERE product_chunks_fts MATCH :q"
    ), {"q": term})).all()
    return len(rows)


async def test_clearing_before_replacement_leaves_no_orphan(db, product_with_index):
    """The ordering that matters: clear while the embedding rows still exist."""
    from sqlalchemy import delete

    assert await _terms_findable(db, "Kurabanda") == 1

    await clear_product_chunk_index(db, product_with_index.id)
    await db.execute(
        delete(ProductEmbedding).where(
            ProductEmbedding.product_id == product_with_index.id
        )
    )
    await db.commit()

    assert await _terms_findable(db, "Kurabanda") == 0


async def test_clearing_after_replacement_strands_the_old_row(db, product_with_index):
    """Documents the hazard the ordering above exists to avoid.

    If the embeddings are deleted first, clear_product_chunk_index has nothing
    left to resolve rowids from, and the stale text stays findable.
    """
    from sqlalchemy import delete

    await db.execute(
        delete(ProductEmbedding).where(
            ProductEmbedding.product_id == product_with_index.id
        )
    )
    await db.commit()
    await clear_product_chunk_index(db, product_with_index.id)
    await db.commit()

    assert await _terms_findable(db, "Kurabanda") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_chunk_fts_sync.py -v`
Expected: both pass already — they test Task 3's functions directly and encode the ordering contract. If `test_clearing_before_replacement_leaves_no_orphan` fails, Task 3 is wrong; stop and fix it before continuing.

- [ ] **Step 3: Clear the index before the embeddings are replaced**

In `backend/grimoire/services/queue_processor.py`, inside `handle_embed_task`, replace this:

```python
    # Now do all DB writes quickly
    await db.execute(
        delete(ProductEmbedding).where(ProductEmbedding.product_id == product.id)
    )
```

with this:

```python
    # Now do all DB writes quickly.
    # ⚠️ The body index is cleared FIRST. Its rowids are embedding ids, so
    # once the rows below are deleted there is nothing left to resolve them
    # from and the old text would stay findable forever.
    from grimoire.services.fts_service import (
        clear_product_chunk_index,
        index_product_chunks,
    )

    await clear_product_chunk_index(db, product.id)
    await db.execute(
        delete(ProductEmbedding).where(ProductEmbedding.product_id == product.id)
    )
```

- [ ] **Step 4: Index the new chunks before returning**

Still in `handle_embed_task`, replace the closing sequence:

```python
    await db.commit()
    invalidate_vector_cache()
    return True
```

with:

```python
    # Flush so the new embedding rows have ids; the body index keys on them.
    await db.flush()
    await index_product_chunks(db, product.id)

    await db.commit()
    invalidate_vector_cache()
    return True
```

- [ ] **Step 5: Write the handler-level test**

Append to `backend/tests/services/test_chunk_fts_sync.py`:

```python
async def test_embed_handler_reindexes_the_body(db, product_with_index, monkeypatch):
    """Re-embedding replaces the indexed text rather than stacking on it."""
    from grimoire.services import queue_processor
    from grimoire.services.embeddings import EmbeddingResult

    async def fake_generate(chunks, *args, **kwargs):
        return [
            EmbeddingResult(embedding=[0.1, 0.2, 0.3], model="test")
            for _ in chunks
        ]

    monkeypatch.setattr(
        "grimoire.services.embeddings.generate_embeddings", fake_generate
    )
    monkeypatch.setattr(
        "grimoire.services.embeddings.build_chunks_for_product",
        lambda preamble, pages, text: [("The Sathar fleet withdraws.", 40, 41)],
    )

    await queue_processor.handle_embed_task(db, product_with_index)

    assert await _terms_findable(db, "Kurabanda") == 0
    assert await _terms_findable(db, "Sathar") == 1
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_chunk_fts_sync.py -v`
Expected: 3 passed.

If `EmbeddingResult` has a different constructor signature, read
`backend/grimoire/services/embeddings.py` and match it rather than guessing —
do not change the assertions to accommodate a broken fake.

- [ ] **Step 7: Run the full suite**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest -q`
Expected: 630 passed, 1 failed (pre-existing).

- [ ] **Step 8: Commit**

```bash
git add backend/grimoire/services/queue_processor.py backend/tests/services/test_chunk_fts_sync.py
git commit -m "feat(fts): keep the body index in step with re-embedding"
```

---

### Task 5: Backfill and orphan sweep

**Files:**
- Modify: `backend/grimoire/services/fts_service.py` (add `prune_orphaned_chunk_index`)
- Modify: `backend/grimoire/services/queue_processor.py` (add a `chunk_fts_index` handler)
- Modify: `backend/grimoire/api/routes/queue.py` (add `POST /queue/fts/rebuild-chunks`)
- Test: `backend/tests/api/test_chunk_fts_backfill.py`

**Interfaces:**
- Consumes: `index_product_chunks`, `clear_product_chunk_index` (Task 3).
- Produces:
  - `async def prune_orphaned_chunk_index(db: AsyncSession) -> int` — rows removed.
  - Queue task type `"chunk_fts_index"`.
  - `POST /api/v1/queue/fts/rebuild-chunks` returning `{"created": int, "skipped": int, "total": int}`.

**Why a sweep rather than a delete hook.** Products are deleted from four
places (`products.py:390` and `duplicate_service.py:269`, `:364`, `:677`).
Hooking each is exactly the fragility that produced dc377a7 — a fifth site
added later would silently leak. `product_embeddings` rows go away by ORM
`delete-orphan`; the sweep removes index rows whose embedding is gone.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/test_chunk_fts_backfill.py`:

```python
"""Backfilling the body index, and sweeping rows their chunks left behind."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from grimoire.database import _ensure_fts_table, get_db
from grimoire.main import app
from grimoire.models import Product, ProductEmbedding
from grimoire.services.fts_service import (
    index_product_chunks,
    prune_orphaned_chunk_index,
)


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def indexed_product(db):
    await _ensure_fts_table(await db.connection())
    product = Product(
        file_path=r"D:\Games\sf1.pdf",
        file_name="sf1.pdf",
        file_size=1024,
        file_hash="sf1hash",
        title="SF1 Volturnus",
        text_extracted=True,
    )
    db.add(product)
    await db.flush()
    emb = ProductEmbedding(
        product_id=product.id,
        chunk_index=0,
        chunk_text="The Kurabanda live in the treetops.",
        embedding_model="test",
        embedding_dim=3,
        page_start=32,
        page_end=33,
    )
    emb.set_embedding_vector([0.1, 0.2, 0.3])
    db.add(emb)
    await db.commit()
    return product


async def _rows(db) -> int:
    return (await db.execute(
        text("SELECT count(*) FROM product_chunks_fts")
    )).scalar_one()


async def test_prune_removes_rows_whose_chunk_is_gone(db, indexed_product):
    """Deleting a product drops its embeddings by ORM cascade; the virtual
    table has no relationship to ride, so the sweep is what cleans it up."""
    await index_product_chunks(db, indexed_product.id)
    await db.commit()
    assert await _rows(db) == 1

    await db.delete(indexed_product)
    await db.commit()

    assert await prune_orphaned_chunk_index(db) == 1
    assert await _rows(db) == 0


async def test_prune_keeps_live_rows(db, indexed_product):
    await index_product_chunks(db, indexed_product.id)
    await db.commit()

    assert await prune_orphaned_chunk_index(db) == 0
    assert await _rows(db) == 1


async def test_rebuild_chunks_queues_products_with_chunks(client, db, indexed_product):
    async with client as c:
        resp = await c.post("/api/v1/queue/fts/rebuild-chunks")

    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 1
    assert body["total"] == 1


async def test_rebuild_chunks_skips_products_already_queued(client, db, indexed_product):
    async with client as c:
        await c.post("/api/v1/queue/fts/rebuild-chunks")
        resp = await c.post("/api/v1/queue/fts/rebuild-chunks")

    assert resp.json()["skipped"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/api/test_chunk_fts_backfill.py -v`
Expected: FAIL with `ImportError: cannot import name 'prune_orphaned_chunk_index'`.

- [ ] **Step 3: Add the sweep**

Append to `backend/grimoire/services/fts_service.py`:

```python
async def prune_orphaned_chunk_index(db: AsyncSession) -> int:
    """Drop body-index rows whose chunk no longer exists. Returns rows removed.

    Products are deleted from four call sites, and their product_embeddings go
    with them by ORM delete-orphan. A virtual table has no relationship to
    ride, and SQLite foreign keys are off, so nothing removes these rows
    automatically. Sweeping is deliberate: hooking every delete site is the
    fragility that produced dc377a7, and a fifth site added later would leak
    silently.

    This is a full scan of the index. It is a maintenance operation, not
    something to call per request.
    """
    result = await db.execute(text("""
        DELETE FROM product_chunks_fts
        WHERE rowid NOT IN (SELECT id FROM product_embeddings)
    """))
    await db.commit()
    return result.rowcount or 0
```

- [ ] **Step 4: Add the queue handler**

In `backend/grimoire/services/queue_processor.py`, beside `handle_fts_index_task`:

```python
@register_handler("chunk_fts_index")
async def handle_chunk_fts_index_task(db: AsyncSession, product: Product) -> bool:
    """Rebuild one product's rows in the body index."""
    from grimoire.services.fts_service import (
        clear_product_chunk_index,
        index_product_chunks,
    )

    await clear_product_chunk_index(db, product.id)
    written = await index_product_chunks(db, product.id)
    await db.commit()

    # Zero is legitimate: a product with no chunks has nothing to index. It is
    # not an error, and raising here would fail thousands of image-only
    # products during the backfill.
    logger.info(f"Chunk FTS index rebuilt for product {product.id}: {written} rows")
    return True
```

- [ ] **Step 5: Add the backfill endpoint**

In `backend/grimoire/api/routes/queue.py`, after `rebuild_fts_index`:

```python
@router.post("/fts/rebuild-chunks")
async def rebuild_chunk_fts_index(
    db: DbSession,
    batch_size: int = Query(100, ge=1, le=1000, description="Batch size"),
) -> dict:
    """Queue every product that has chunks for body indexing."""
    from grimoire.models import ProductEmbedding

    product_ids = (await db.execute(
        select(ProductEmbedding.product_id).distinct()
    )).scalars().all()

    created = 0
    skipped = 0

    for product_id in product_ids:
        existing = await db.execute(
            select(ProcessingQueue).where(
                ProcessingQueue.product_id == product_id,
                ProcessingQueue.task_type == "chunk_fts_index",
                ProcessingQueue.status.in_(["pending", "processing"]),
            )
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        db.add(ProcessingQueue(
            product_id=product_id,
            task_type="chunk_fts_index",
            priority=8,
            status="pending",
        ))
        created += 1

    await db.commit()

    return {
        "message": f"Queued {created} products for body indexing",
        "created": created,
        "skipped": skipped,
        "total": len(product_ids),
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/api/test_chunk_fts_backfill.py -v`
Expected: 4 passed.

- [ ] **Step 7: Run the full suite**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest -q`
Expected: 634 passed, 1 failed (pre-existing).

- [ ] **Step 8: Measure index growth on a subset**

The spec requires a real measurement before committing to 3.3M chunks, because
FTS5 overhead scales with vocabulary and OCR noise inflates vocabulary badly.

⚠️ Do **not** copy `grimoire.db` to measure this — it is 16 GB. Save the script
below as `backend/scripts/probe_index_size.py` and run it from `backend/`. It
ATTACHes a fresh empty database, builds the probe index there, reports, and
deletes it. The live database is only ever read.

```python
"""Throwaway probe: project full body-index size from a subset."""
import os
import sqlite3

PROBE = "probe-index.db"
SAMPLE = 200_000

if os.path.exists(PROBE):
    os.remove(PROBE)

conn = sqlite3.connect("data/grimoire.db")
conn.execute("ATTACH DATABASE ? AS probe", (PROBE,))
conn.execute(
    "CREATE VIRTUAL TABLE probe.probe_fts USING fts5("
    " chunk_text, product_id UNINDEXED, chunk_index UNINDEXED,"
    " page_start UNINDEXED, page_end UNINDEXED)"
)
conn.execute(
    "INSERT INTO probe.probe_fts("
    " rowid, chunk_text, product_id, chunk_index, page_start, page_end)"
    " SELECT id, chunk_text, product_id, chunk_index, page_start, page_end"
    " FROM product_embeddings LIMIT ?",
    (SAMPLE,),
)
conn.commit()
sampled = conn.execute("SELECT count(*) FROM probe.probe_fts").fetchone()[0]
total = conn.execute("SELECT count(*) FROM product_embeddings").fetchone()[0]
conn.execute("DETACH DATABASE probe")
conn.close()

size = os.path.getsize(PROBE)
os.remove(PROBE)

print("indexed %d of %d chunks -> %.2f GB" % (sampled, total, size / 1e9))
print("full index projects to %.2f GB" % (size / sampled * total / 1e9))
```

Run: `C:/Users/mkemi/miniconda3/python.exe scripts/probe_index_size.py`

Record the projection. The spec estimates ~1.5 GB of text plus ~1–1.5 GB of
index. If the projection lands far above that, stop and report before Task 9's
full backfill — it is an argument for normalizing indexed text, which is out
of scope here and needs its own decision.

- [ ] **Step 9: Commit**

```bash
git add backend/grimoire/services/fts_service.py backend/grimoire/services/queue_processor.py backend/grimoire/api/routes/queue.py backend/tests/api/test_chunk_fts_backfill.py
git commit -m "feat(fts): backfill the body index, and sweep rows their chunks left behind"
```

---

### Task 6: Query the body index

**Files:**
- Modify: `backend/grimoire/services/fts_service.py` (add `chunk_candidates` after `fts_candidates`)
- Test: `backend/tests/services/test_chunk_candidates.py`

**Interfaces:**
- Consumes: `product_chunks_fts` (Task 2), `build_fts_match` (existing, `fts_service.py:26`).
- Produces: `async def chunk_candidates(db, query, game_system=None, product_type=None, limit=150) -> list[tuple[int, float, str, int | None]]` — `(product_id, score, snippet, page_start)`, best chunk per product, score descending.

⚠️ **Carry the unary `+`.** See Global Constraints. A query without it takes
~87 s instead of ~0.03 s, and no test will notice unless it times.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_chunk_candidates.py`:

```python
"""Selecting candidate products from the body index."""
import pytest
from sqlalchemy import text

from grimoire.database import _ensure_fts_table
from grimoire.models import Product, ProductEmbedding
from grimoire.services.fts_service import chunk_candidates, index_product_chunks


async def _make(db, *, title, file_hash, chunks, game_system=None, is_duplicate=False):
    product = Product(
        file_path=rf"D:\Games\{file_hash}.pdf",
        file_name=f"{file_hash}.pdf",
        file_size=1024,
        file_hash=file_hash,
        title=title,
        game_system=game_system,
        is_duplicate=is_duplicate,
        text_extracted=True,
    )
    db.add(product)
    await db.flush()
    for i, (body, page) in enumerate(chunks):
        emb = ProductEmbedding(
            product_id=product.id,
            chunk_index=i,
            chunk_text=body,
            embedding_model="test",
            embedding_dim=3,
            page_start=page,
            page_end=page,
        )
        emb.set_embedding_vector([0.1, 0.2, 0.3])
        db.add(emb)
    await db.commit()
    await index_product_chunks(db, product.id)
    await db.commit()
    return product


@pytest.fixture
async def library(db):
    await _ensure_fts_table(await db.connection())
    sf1 = await _make(
        db, title="SF1 Volturnus", file_hash="sf1",
        chunks=[
            ("The party lands in a damaged shuttle.", 2),
            ("The Kurabanda live in the treetops. Kurabanda scouts watch.", 32),
        ],
        game_system="Star Frontiers",
    )
    other = await _make(
        db, title="Frontier Explorer", file_hash="fe",
        chunks=[("A single mention of Kurabanda in passing.", 5)],
        game_system="Star Frontiers",
    )
    dupe = await _make(
        db, title="SF1 Volturnus (copy)", file_hash="dupe",
        chunks=[("The Kurabanda live in the treetops.", 32)],
        is_duplicate=True,
    )
    return {"sf1": sf1, "other": other, "dupe": dupe}


async def test_finds_a_product_by_deep_body_text(db, library):
    hits = await chunk_candidates(db, "Kurabanda")

    assert library["sf1"].id in [pid for pid, _, _, _ in hits]


async def test_returns_the_page_of_the_matching_chunk(db, library):
    hits = await chunk_candidates(db, "Kurabanda")
    by_id = {pid: (snippet, page) for pid, _, snippet, page in hits}

    _, page = by_id[library["sf1"].id]
    assert page == 32


async def test_returns_one_row_per_product(db, library):
    """A product is scored by its single best chunk, matching TOP_K_CHUNKS=1."""
    hits = await chunk_candidates(db, "Kurabanda")
    ids = [pid for pid, _, _, _ in hits]

    assert len(ids) == len(set(ids))


async def test_snippet_contains_the_matched_term(db, library):
    hits = await chunk_candidates(db, "Kurabanda")
    by_id = {pid: snippet for pid, _, snippet, _ in hits}

    assert "Kurabanda" in by_id[library["sf1"].id]


async def test_duplicates_are_excluded(db, library):
    hits = await chunk_candidates(db, "Kurabanda")

    assert library["dupe"].id not in [pid for pid, _, _, _ in hits]


async def test_game_system_filter_applies(db, library):
    hits = await chunk_candidates(db, "Kurabanda", game_system="Traveller")

    assert hits == []


async def test_limit_is_respected(db, library):
    hits = await chunk_candidates(db, "Kurabanda", limit=1)

    assert len(hits) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_chunk_candidates.py -v`
Expected: FAIL with `ImportError: cannot import name 'chunk_candidates'`.

- [ ] **Step 3: Add the query**

Append to `backend/grimoire/services/fts_service.py`:

```python
async def chunk_candidates(
    db: AsyncSession,
    query: str,
    game_system: str | None = None,
    product_type: str | None = None,
    limit: int = 150,
) -> list[tuple[int, float, str, int | None]]:
    """Candidate products from the body index, best chunk each.

    Returns (product_id, score, snippet, page_start) sorted by score
    descending. A product is scored by its single best chunk, matching
    TOP_K_CHUNKS = 1 on the semantic side.
    """
    match = build_fts_match(query)
    if match is None:
        return []

    # The unary + on the boolean columns is load-bearing: without it SQLite
    # drives the join from ix_products_is_duplicate and re-runs the MATCH once
    # per product (~87s). + disqualifies those indexes so the MATCH drives.
    # Do not remove. Same reasoning as fts_candidates above.
    sql = text("""
        SELECT
            f.product_id,
            MIN(bm25(product_chunks_fts)) AS rank,
            snippet(product_chunks_fts, 0, '<mark>', '</mark>', '...', 32) AS snippet,
            f.page_start
        FROM product_chunks_fts f
        JOIN products p ON p.id = f.product_id
        WHERE product_chunks_fts MATCH :query
        AND +p.is_duplicate = 0
        AND +p.is_missing = 0
        AND (:game_system IS NULL OR p.game_system = :game_system)
        AND (:product_type IS NULL OR p.product_type = :product_type)
        GROUP BY f.product_id
        ORDER BY rank
        LIMIT :limit
    """)

    try:
        result = await db.execute(sql, {
            "query": match,
            "game_system": game_system,
            "product_type": product_type,
            "limit": limit,
        })
        # bm25 is negative (more negative = better); callers expect a magnitude.
        return [
            (row[0], abs(row[1]), row[2] or "", row[3])
            for row in result.fetchall()
        ]
    except Exception as e:
        logger.warning(f"Chunk FTS candidate search failed: {e}")
        return []
```

⚠️ `MIN(bm25(...))` picks the best chunk because bm25 is negative. The
`snippet` and `page_start` selected alongside a bare `GROUP BY` come from
SQLite's bare-column rule, which pairs them with the row chosen by `MIN()`.
This is SQLite-specific and intentional. If the test asserting `page == 32`
fails, that guarantee is not holding — rewrite as a correlated subquery
rather than loosening the assertion.

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_chunk_candidates.py -v`
Expected: 7 passed.

- [ ] **Step 5: Verify the query plan lets MATCH drive**

Run from `backend/`:

```bash
C:/Users/mkemi/miniconda3/python.exe -c "
import sqlite3
c = sqlite3.connect('data/grimoire.db')
plan = c.execute('''EXPLAIN QUERY PLAN
    SELECT f.product_id, MIN(bm25(product_chunks_fts))
    FROM product_chunks_fts f JOIN products p ON p.id = f.product_id
    WHERE product_chunks_fts MATCH 'kurabanda'
    AND +p.is_duplicate = 0 AND +p.is_missing = 0
    GROUP BY f.product_id''').fetchall()
for r in plan: print(r)
"
```

Expected: `product_chunks_fts` appears as a VIRTUAL TABLE INDEX scan first and
`products` is reached by its primary key. If `products` is scanned via
`ix_products_is_duplicate` instead, the `+` has been lost — fix before
continuing.

- [ ] **Step 6: Run the full suite**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest -q`
Expected: 641 passed, 1 failed (pre-existing).

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/services/fts_service.py backend/tests/services/test_chunk_candidates.py
git commit -m "feat(search): select candidates from the chunk body index"
```

---

### Task 7: Feed body hits into search

**Files:**
- Modify: `backend/grimoire/services/search_service.py` (`search`, the Stage 1 block and the `best_chunk` assembly)
- Test: `backend/tests/services/test_search_body_hits.py`

**Interfaces:**
- Consumes: `chunk_candidates` (Task 6).
- Produces: `search()` returns products matched only on deep body text, with a snippet and page.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_search_body_hits.py`:

```python
"""A term only in deep body text must reach the results.

This is the failure the whole plan exists to fix: BM25 over the first 50,000
characters could never nominate such a product for Stage 1, so Stage 2 never
saw it, however good the chunk re-rank was.
"""
import pytest

from grimoire.database import _ensure_fts_table
from grimoire.models import Product, ProductEmbedding
from grimoire.services.fts_service import chunk_candidates, index_product_chunks


@pytest.fixture
async def deep_book(db):
    await _ensure_fts_table(await db.connection())
    product = Product(
        file_path=r"D:\Games\sf1.pdf",
        file_name="sf1.pdf",
        file_size=1024,
        file_hash="sf1hash",
        title="SF1 Volturnus Planet of Mystery",
        text_extracted=True,
    )
    db.add(product)
    await db.flush()
    # Chunk 400 stands in for text far past the old 50,000-char cap.
    emb = ProductEmbedding(
        product_id=product.id,
        chunk_index=400,
        chunk_text="The Kurabanda live in the treetops of Volturnus.",
        embedding_model="test",
        embedding_dim=3,
        page_start=32,
        page_end=33,
    )
    emb.set_embedding_vector([0.1, 0.2, 0.3])
    db.add(emb)
    await db.commit()
    await index_product_chunks(db, product.id)
    await db.commit()
    return product


async def test_body_only_term_produces_a_candidate(db, deep_book):
    hits = await chunk_candidates(db, "Kurabanda")

    assert [pid for pid, _, _, _ in hits] == [deep_book.id]


async def test_the_candidate_carries_snippet_and_page(db, deep_book):
    """Today best_chunk is filled only by the semantic re-rank, so a product
    that surfaces purely on keywords shows no snippet at all."""
    (_, _, snippet, page), = await chunk_candidates(db, "Kurabanda")

    assert "Kurabanda" in snippet
    assert page == 32
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_search_body_hits.py -v`
Expected: 2 passed — they exercise Task 6 directly and pin the contract Step 3 wires in.

- [ ] **Step 3: Merge body hits into Stage 1**

In `backend/grimoire/services/search_service.py`, import the new query beside
the existing one:

```python
from grimoire.services.fts_service import chunk_candidates, fts_candidates  # noqa: E402
```

Then, in `search`, replace this block:

```python
    keyword_ranking: list[tuple[int, float]] = []
    try:
        fts_pairs = await fts_candidates(
            db, semantic_query,
            game_system=request.game_system,
            product_type=request.product_type,
            limit=CANDIDATES_PER_SOURCE,
        )
        keyword_ranking = [
            (pid, score) for pid, score in fts_pairs
            if allowed is None or pid in allowed
        ]
    except Exception:
        logger.warning("FTS failed during search; continuing semantic-only")
```

with:

```python
    keyword_ranking: list[tuple[int, float]] = []
    keyword_chunk: dict[int, tuple[str, int | None]] = {}
    try:
        fts_pairs = await fts_candidates(
            db, semantic_query,
            game_system=request.game_system,
            product_type=request.product_type,
            limit=CANDIDATES_PER_SOURCE,
        )
        # Body hits are a second keyword source. Metadata and body compete on
        # one merged list rather than one crowding the other out of the cut.
        body_hits = await chunk_candidates(
            db, semantic_query,
            game_system=request.game_system,
            product_type=request.product_type,
            limit=CANDIDATES_PER_SOURCE,
        )

        best: dict[int, float] = {}
        for pid, score in fts_pairs:
            best[pid] = max(best.get(pid, 0.0), score)
        for pid, score, snippet, page in body_hits:
            best[pid] = max(best.get(pid, 0.0), score)
            keyword_chunk[pid] = (snippet, page)

        keyword_ranking = [
            (pid, score)
            for pid, score in sorted(best.items(), key=lambda kv: -kv[1])
            if allowed is None or pid in allowed
        ][:CANDIDATES_PER_SOURCE]
    except Exception:
        logger.warning("FTS failed during search; continuing semantic-only")
```

- [ ] **Step 4: Let keyword-only hits carry a snippet**

Still in `search`, replace:

```python
    best_chunk = {pid: (text, page) for pid, _, text, page in semantic_ranking}
```

with:

```python
    # The semantic re-rank wins where both have an opinion: it scored the chunk
    # on meaning, while the keyword side only knows a term appeared in it.
    best_chunk = dict(keyword_chunk)
    best_chunk.update({pid: (text, page) for pid, _, text, page in semantic_ranking})
```

- [ ] **Step 5: Run the full suite**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest -q`
Expected: 643 passed, 1 failed (pre-existing). Pay attention to
`tests/services/test_search_flow.py` and `test_hybrid_search.py` — if either
breaks, the merge changed ranking in a way those tests pin, and that is a real
signal, not a test to update casually.

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/services/search_service.py backend/tests/services/test_search_body_hits.py
git commit -m "feat(search): let deep body matches nominate and annotate results"
```

---

### Task 8: Retire the truncated body from products_fts

Only now, with the body served from its own index, does removing the old one
stop being a regression.

**Files:**
- Modify: `backend/grimoire/database.py` (`_ensure_fts_table`: the `CREATE VIRTUAL TABLE` for `products_fts`, the description-column migration probe, and the backfill)
- Modify: `backend/grimoire/services/fts_service.py` (`update_search_vector`, `search_fts`)
- Delete: `backend/tests/services/test_fts_trigger_preserves_text.py`
- Test: `backend/tests/services/test_products_fts_metadata_only.py`

`handle_fts_index_task` is deliberately untouched: `update_search_vector`
keeps its name and signature and becomes a metadata-only refresh, so its
caller needs no change.

**Interfaces:**
- Consumes: Tasks 2–7 complete; body searchable from `product_chunks_fts`.
- Produces: `products_fts` with six columns and no body.

⚠️ **`search_fts` calls `snippet(products_fts, 6, ...)` and column 6 IS
`extracted_text`.** Dropping the column silently changes what column 6 means.
This yields wrong snippets rather than an error, so it must be changed in the
same commit.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_products_fts_metadata_only.py`:

```python
"""products_fts holds metadata and nothing else.

Sharing one table between the metadata trigger and the body writer is what
produced dc377a7. The body now lives in product_chunks_fts, so the shared
ownership goes away rather than being managed.
"""
from sqlalchemy import text

from grimoire.database import _ensure_fts_table


async def _columns(db) -> list[str]:
    rows = (await db.execute(text("PRAGMA table_info(products_fts)"))).all()
    return [r[1] for r in rows]


async def test_products_fts_has_no_body_column(db):
    await _ensure_fts_table(await db.connection())

    assert await _columns(db) == [
        "title", "file_name", "publisher", "game_system",
        "product_type", "description",
    ]


async def test_existing_seven_column_table_is_migrated(db):
    """Databases in the wild carry the old seven-column table."""
    conn = await db.connection()
    await db.execute(text("DROP TABLE IF EXISTS products_fts"))
    await db.execute(text("""
        CREATE VIRTUAL TABLE products_fts USING fts5(
            title, file_name, publisher, game_system, product_type,
            description, extracted_text
        )
    """))

    await _ensure_fts_table(conn)

    assert "extracted_text" not in await _columns(db)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_products_fts_metadata_only.py -v`
Expected: FAIL — the column list still ends with `extracted_text`.

- [ ] **Step 3: Drop the column from the schema**

In `backend/grimoire/database.py`, in `_ensure_fts_table`, change the creation
statement from:

```python
            CREATE VIRTUAL TABLE products_fts USING fts5(
                title, file_name, publisher, game_system, product_type,
                description, extracted_text
            )
```

to:

```python
            CREATE VIRTUAL TABLE products_fts USING fts5(
                title, file_name, publisher, game_system, product_type,
                description
            )
```

There are two such statements in this function — the initial creation and the
rebuild inside the description-column migration. Change both.

- [ ] **Step 4: Migrate existing databases**

Still in `_ensure_fts_table`, replace the description-column probe:

```python
        try:
            await conn.execute(text(
                "SELECT description FROM products_fts LIMIT 0"
            ))
        except Exception:
```

with a probe that also rebuilds when the obsolete body column is still present:

```python
        needs_rebuild = False
        try:
            await conn.execute(text(
                "SELECT description FROM products_fts LIMIT 0"
            ))
        except Exception:
            needs_rebuild = True
        else:
            # The body moved to product_chunks_fts. An existing table still
            # carrying extracted_text has to be rebuilt, or snippet() column
            # offsets in search_fts silently point at the wrong column.
            try:
                await conn.execute(text(
                    "SELECT extracted_text FROM products_fts LIMIT 0"
                ))
                needs_rebuild = True
            except Exception:
                pass

        if needs_rebuild:
```

Keep the existing body of that branch (drop table, recreate, drop triggers,
`created_new = True`) unchanged beneath it, with the six-column `CREATE` from
Step 3.

- [ ] **Step 5: Stop writing the body, and fix the snippet column**

In `backend/grimoire/services/fts_service.py`, replace the whole body of
`update_search_vector` — the JSON read, the 50,000-char truncation, the DELETE
and the INSERT — with a metadata-only refresh:

```python
async def update_search_vector(db: AsyncSession, product: Product) -> bool:
    """Refresh a product's metadata row in the FTS index.

    The body is no longer written here. It lives in product_chunks_fts, keyed
    by chunk and carrying page numbers, written by index_product_chunks. This
    function used to read the extraction JSON and index its first 50,000
    characters, which hid 71% of the library's text from keyword search.
    """
    try:
        await db.execute(
            text("DELETE FROM products_fts WHERE rowid = :product_id"),
            {"product_id": product.id},
        )
        await db.execute(
            text("""
                INSERT INTO products_fts(rowid, title, file_name, publisher,
                                         game_system, product_type, description)
                VALUES (:product_id, :title, :file_name, :publisher,
                        :game_system, :product_type, :description)
            """),
            {
                "product_id": product.id,
                "title": product.title or "",
                "file_name": product.file_name or "",
                "publisher": product.publisher or "",
                "game_system": product.game_system or "",
                "product_type": product.product_type or "",
                "description": product.description or "",
            },
        )

        product.deep_indexed = True
        await db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to update FTS index for product {product.id}: {e}")
        return False
```

In the same file, in `search_fts`, change:

```python
            snippet(products_fts, 6, '<mark>', '</mark>', '...', 32) as snippet
```

to draw the snippet from the title column, which still exists:

```python
            snippet(products_fts, 0, '<mark>', '</mark>', '...', 32) as snippet
```

- [ ] **Step 6: Run the full suite**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest -q`
Expected: 642 passed, 1 failed (pre-existing). The count goes *down*: two
tests are added here and three are deleted with the file below.

`tests/services/test_fts_trigger_preserves_text.py` asserts that a body
survives a product update. Its subject no longer exists in this table. Delete
that file in this commit — the behaviour it protected is now structural, and
`test_products_fts_metadata_only.py` covers the replacement. Do not weaken its
assertions to keep it passing.

- [ ] **Step 7: Commit**

```bash
git rm backend/tests/services/test_fts_trigger_preserves_text.py
git add backend/grimoire/database.py backend/grimoire/services/fts_service.py backend/tests/services/test_products_fts_metadata_only.py
git commit -m "refactor(fts): products_fts holds metadata only

The body moved to product_chunks_fts, so the shared ownership that produced
dc377a7 is gone rather than managed. search_fts drew its snippet from column
6, which was extracted_text - dropping the column silently repoints that
offset, so it moves to the title column in the same change."
```

---

### Task 9: Backfill the library and prove the result

**Files:** none — this task is a measurement, not a change.

**Interfaces:**
- Consumes: everything above, plus `backend/runs/deep-text-baseline.json` (Task 1).
- Produces: a recorded before/after comparison.

- [ ] **Step 1: Restart the app**

The new tables and the migrated `products_fts` are created by
`_ensure_fts_table` at startup, so the running instance must be restarted.

Run `start.bat` from the repo root in an interactive terminal.
⚠️ `start.bat` ends in `pause`; it cannot be launched headlessly — run it
where stdin is a real console, or it exits immediately and kills what it
started.

- [ ] **Step 2: Confirm the schema migrated**

```bash
C:/Users/mkemi/miniconda3/python.exe -c "
import sqlite3
c = sqlite3.connect(r'C:\Users\mkemi\Projects\grimoire\backend\data\grimoire.db')
print('products_fts     :', [r[1] for r in c.execute('pragma table_info(products_fts)')])
print('product_chunks_fts:', [r[1] for r in c.execute('pragma table_info(product_chunks_fts)')])
"
```

Expected: `products_fts` has six columns and no `extracted_text`;
`product_chunks_fts` exists.

- [ ] **Step 3: Queue the backfill**

```bash
curl -s -X POST "http://localhost:8000/api/v1/queue/fts/rebuild-chunks"
```

Expected: `created` in the region of 19,000.

- [ ] **Step 4: Run the worker**

```bash
curl -s -X POST http://localhost:8000/api/v1/queue/resume
```

Then poll until `pending` reaches zero:

```bash
curl -s http://localhost:8000/api/v1/queue/stats
```

Record how long the backfill took and whether `failed` rose. A rising failure
count means stop and investigate, not proceed.

- [ ] **Step 5: Sweep orphans**

```bash
C:/Users/mkemi/miniconda3/python.exe -c "
import asyncio, sys
sys.path.insert(0, '.')
from grimoire.database import async_session_maker
from grimoire.services.fts_service import prune_orphaned_chunk_index

async def main():
    async with async_session_maker() as db:
        print('pruned:', await prune_orphaned_chunk_index(db))
asyncio.run(main())
"
```

Run from `backend/`. A large number here means a delete path is leaking and
should be investigated before it is normalised.

- [ ] **Step 6: Prove the acceptance case**

```bash
C:/Users/mkemi/miniconda3/python.exe -c "
import asyncio, sys
sys.path.insert(0, '.')
from grimoire.database import async_session_maker
from grimoire.services.fts_service import chunk_candidates

async def main():
    async with async_session_maker() as db:
        for pid, score, snippet, page in (await chunk_candidates(db, 'Kurabanda'))[:5]:
            print(pid, round(score, 3), 'p.%s' % page, snippet[:70])
asyncio.run(main())
"
```

Expected: *SF1 Volturnus Planet of Mystery* appears with a page in the low 30s
and a snippet containing the term. This is the query that returned nothing
when the work began.

Pick a second case from a p90-sized book — one where under 10% was previously
indexed — and confirm a term from its final quarter is now findable.

- [ ] **Step 7: Confirm latency did not regress**

Re-run the latency probe from Task 1, Step 3. Compare against the recorded
numbers. Anything in the tens of seconds means the `+` has been lost somewhere.

- [ ] **Step 8: Compare search quality against the baseline**

```bash
C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py --compare runs/deep-text-baseline.json
```

The bar is **no regression** in hit@k or MRR. An improvement is expected but is
not what is being tested for. If either metric drops, report the numbers rather
than retuning constants — `KEYWORD_RRF_WEIGHT` and its neighbours were tuned
against this harness and re-tuning is a separate exercise with its own
before/after measurement.

- [ ] **Step 9: Record the outcome**

Append a short outcome section to this plan: the backfill duration, the final
index size against the Task 5 projection, the before/after eval numbers, the
latency comparison, and whether the acceptance cases passed. Note anything that
behaved differently from what this plan predicted.

---

## Notes for the implementer

**Why the ordering in Task 4 is not a style preference.** The body index keys
its rowid to `ProductEmbedding.id` because `product_id` is UNINDEXED, and
filtering an FTS5 table on an unindexed column scans every row — 3.3M of them,
per product. That choice buys a fast delete and costs a strict ordering
requirement: clear the index while the embedding rows still exist. Task 4 has
a test that deliberately documents the wrong order and asserts the stale row
survives, so the hazard is pinned rather than remembered.

**Why there is a sweep instead of delete hooks.** Products are deleted from
four call sites today. Hooking each is the same fragility that produced
dc377a7, where one trigger drifted from the schema it served and nothing
noticed for months. The sweep is O(index) and runs as maintenance, not per
request.

**What this plan deliberately does not do.** It does not normalize OCR text
before indexing. The extraction contains real garbage runs —
`cesscerocececeenscoessceeeees` appears in SF1's own text — and every such run
is unique tokens inflating the FTS vocabulary. The standalone table is chosen
partly so that indexed text *can* later diverge from displayed text, but doing
it needs its own measurement of how much noise is present and what
normalization costs in recall. Task 5, Step 8 is where that decision gets its
first real evidence.

**Chunk boundaries can split words.** Chunks cap at 500 characters and overlap,
and coverage sampling found 119 of 120 tail terms present across six large
books; the single miss was in a 1.66M-character book and is consistent with a
term split across a boundary. This is a known characteristic, not a defect to
chase — but if a specific search misses a term that is demonstrably in the
document, that is the first thing to check.
