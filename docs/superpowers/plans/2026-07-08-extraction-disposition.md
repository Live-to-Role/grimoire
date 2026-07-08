# Extraction Disposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop re-running text extraction / AI-identify on PDFs that are image collections or have no extractable text, by flagging them terminally and gating every re-queue path, plus a one-time reclassification of the existing failed backlog and a small review/override UI.

**Architecture:** Two new `Product` boolean/text columns (`text_unextractable`, `extraction_error`) plus the existing `is_image_content` form the per-product disposition. Handlers set the flag only on *permanent* (per-product) no-text conditions; a pure `classify_extraction_failure` helper distinguishes permanent from transient by error text. All re-queue queries exclude flagged products. A UI-triggered endpoint reclassifies existing failures; another retries flagged products after extraction improves.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.x async, aiosqlite, pytest; React 19 + TypeScript (strict, `verbatimModuleSyntax`), Vite.

**Spec:** `docs/superpowers/specs/2026-07-08-extraction-disposition-design.md`

**Branch:** `feat/extraction-disposition` (already checked out; already contains the "Re-extract All (force)" button commit).

---

## Environment & Conventions (read first)

- **Backend test runner:** `C:/Users/mkemi/miniconda3/python.exe -m pytest` run from `backend/`. The project `.venv` has NO pytest — use `backend/.venv/Scripts/python.exe` only for import sanity checks.
  - Baseline before starting: **195 passed, 6 pre-existing failures** (diagnostics ×2 — order-dependent, pass in isolation; products-list ×1; scanner-batch ×1; backup-routes ×2). Do not fix those; do not add new failures.
- **Frontend:** from `frontend/`, gate is `npx tsc -b`. Baseline: exactly one pre-existing error `src/pages/Settings.tsx(3,137): 'Shield' ... never read` (not ours). No frontend test framework — do not add one.
- **DB migration:** new columns go in `backend/grimoire/database.py::_ensure_columns()` (the `ALTER TABLE ... ADD COLUMN` list) AND as mapped columns in `models/product.py`. The in-memory test DB is created from the models via `Base.metadata.create_all`, so tests see the columns automatically.
- **Route handlers commit explicitly** — `get_db()` does not auto-commit.
- **Guardrails:** only modify the files each task names; only `git add` those files. Leave unrelated pre-existing working-tree changes and untracked files alone (never `git add -A`). Do not run `python -m grimoire.worker.run` (hangs). Do not trigger the live reclassify/re-extract against the running app.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `backend/grimoire/models/product.py` | `text_unextractable`, `extraction_error` columns | Modify |
| `backend/grimoire/database.py` | `_ensure_columns` rows for the two columns | Modify |
| `backend/grimoire/services/extraction_classifier.py` | Pure permanent/transient failure classifier | **Create** |
| `backend/grimoire/services/queue_processor.py` | Handler flagging; ai_identify + embed-requeue gating | Modify |
| `backend/grimoire/services/scanner.py` | Gate scan-time text auto-queue | Modify |
| `backend/grimoire/api/routes/queue.py` | Gate queue-all; reclassify + retry-unextractable endpoints | Modify |
| `backend/grimoire/api/routes/library.py` | Flagged counts in stats | Modify |
| `frontend/src/pages/LibraryManagement.tsx` | Summary + two buttons | Modify |
| `backend/tests/...` | Unit tests per task | Create |

---

## Task 1: Add the disposition columns

**Files:**
- Modify: `backend/grimoire/models/product.py`
- Modify: `backend/grimoire/database.py`
- Test: `backend/tests/test_extraction_disposition_model.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_extraction_disposition_model.py`:

```python
"""The Product model exposes the extraction-disposition columns."""
from grimoire.models.product import Product


def test_product_has_disposition_columns():
    cols = set(Product.__table__.columns.keys())
    assert "text_unextractable" in cols
    assert "extraction_error" in cols


def test_disposition_defaults_are_falsey():
    # Column default (DDL) is False; a fresh unmapped instance is None for both.
    p = Product(file_path="/t/x.pdf", file_name="x.pdf", file_size=1, file_hash="h")
    assert getattr(p, "text_unextractable", "missing") in (None, False)
    assert getattr(p, "extraction_error", "missing") in (None, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_extraction_disposition_model.py -v`
Expected: FAIL — `AssertionError` (columns absent).

- [ ] **Step 3: Add the mapped columns**

In `backend/grimoire/models/product.py`, find:

```python
    is_image_content: Mapped[bool] = mapped_column(Boolean, default=False)
    images_extracted: Mapped[bool] = mapped_column(Boolean, default=False)
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Add immediately after that block:

```python
    # Extraction disposition: set when a PDF is permanently unextractable
    # (encrypted/corrupt/no text after OCR). Excluded from re-queue paths.
    text_unextractable: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

(`Boolean`, `Text`, `Mapped`, `mapped_column` are already imported in this file.)

- [ ] **Step 4: Add the migration rows**

In `backend/grimoire/database.py`, find the `migrations` list in `_ensure_columns` and the line:

```python
        ("products", "image_count", "INTEGER"),
```

Add immediately after it:

```python
        ("products", "text_unextractable", "BOOLEAN DEFAULT 0"),
        ("products", "extraction_error", "TEXT"),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_extraction_disposition_model.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/models/product.py backend/grimoire/database.py backend/tests/test_extraction_disposition_model.py
git commit -m "feat(model): add text_unextractable + extraction_error disposition columns"
```

---

## Task 2: Permanent/transient failure classifier

**Files:**
- Create: `backend/grimoire/services/extraction_classifier.py`
- Test: `backend/tests/services/test_extraction_classifier.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_extraction_classifier.py`:

```python
"""classify_extraction_failure: permanent (per-product) vs transient (environmental)."""
import pytest
from grimoire.services.extraction_classifier import classify_extraction_failure


@pytest.mark.parametrize("msg", [
    "PDF is encrypted",
    "password required",
    "Cannot open document: FileDataError",
    "corrupt pdf",
    "no text after ocr",
    "Product 5 has no text layer",
])
def test_permanent_signals(msg):
    assert classify_extraction_failure(msg) == "permanent"


@pytest.mark.parametrize("msg", [
    "Connection refused to ollama",
    "tesseract not installed",
    "Read timed out",
    "[Errno 13] Permission denied",
    "429 rate limit",
    "some unrecognised failure",   # unknown -> conservative transient
    "",
    None,
])
def test_transient_or_unknown(msg):
    assert classify_extraction_failure(msg) == "transient"


def test_transient_wins_when_both_present():
    # A permanent-looking word inside an environmental error stays retryable.
    assert classify_extraction_failure("ollama connection: model corrupt?") == "transient"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_extraction_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError: grimoire.services.extraction_classifier`.

- [ ] **Step 3: Create the classifier**

Create `backend/grimoire/services/extraction_classifier.py`:

```python
"""Classify an extraction/identify failure as permanent (per-product) or transient.

Permanent  -> the PDF itself can never be extracted/identified (encrypted, corrupt,
              no text). Safe to flag the product and stop re-queueing.
Transient  -> environmental/config (provider down, tooling missing, I/O). Must stay
              retryable — never flag the product for these.

Conservative by design: only 'permanent' when a permanent signal is present AND no
transient signal is present. Everything else is 'transient'.
"""

PERMANENT_SIGNALS = (
    "encrypted",
    "password",
    "corrupt",
    "damaged",
    "cannot open document",
    "cannot open broken document",
    "filedataerror",
    "format error",
    "no text after ocr",
    "no text layer",
    "no embeddable text",
    "no extractable text",
)

TRANSIENT_SIGNALS = (
    "connection",
    "timeout",
    "timed out",
    "ollama",
    "tesseract",
    "not available",
    "not installed",
    "errno",
    "permission denied",
    "temporarily",
    "rate limit",
    "429",
    "502",
    "503",
)


def classify_extraction_failure(error_message: str | None) -> str:
    """Return 'permanent' or 'transient' for a failure message."""
    msg = (error_message or "").lower()
    if any(sig in msg for sig in TRANSIENT_SIGNALS):
        return "transient"
    if any(sig in msg for sig in PERMANENT_SIGNALS):
        return "permanent"
    return "transient"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_extraction_classifier.py -v`
Expected: PASS (all parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/extraction_classifier.py backend/tests/services/test_extraction_classifier.py
git commit -m "feat(services): permanent/transient extraction-failure classifier"
```

---

## Task 3: Gate the text-extraction queue-all endpoint

**Files:**
- Modify: `backend/grimoire/api/routes/queue.py`
- Test: `backend/tests/api/test_queue_all_gating.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/test_queue_all_gating.py`:

```python
"""queue-all (default + force) must skip image-only / unextractable products."""
import pytest
from httpx import AsyncClient, ASGITransport

from grimoire.main import app
from grimoire.database import get_db
from grimoire.models.product import Product
from grimoire.models import ProcessingQueue
from sqlalchemy import select


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


async def _count_text_items(db, product_id):
    res = await db.execute(
        select(ProcessingQueue).where(
            ProcessingQueue.product_id == product_id,
            ProcessingQueue.task_type == "text",
        )
    )
    return len(list(res.scalars().all()))


@pytest.mark.asyncio
async def test_queue_all_skips_flagged(client, db):
    normal = Product(file_path="/t/n.pdf", file_name="n.pdf", file_size=1, file_hash="n")
    image = Product(file_path="/t/i.pdf", file_name="i.pdf", file_size=1, file_hash="i",
                    is_image_content=True)
    dead = Product(file_path="/t/d.pdf", file_name="d.pdf", file_size=1, file_hash="d",
                   text_unextractable=True)
    db.add_all([normal, image, dead])
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/queue/text-extraction/queue-all")
    assert resp.status_code == 200

    assert await _count_text_items(db, normal.id) == 1
    assert await _count_text_items(db, image.id) == 0
    assert await _count_text_items(db, dead.id) == 0


@pytest.mark.asyncio
async def test_queue_all_force_also_skips_flagged(client, db):
    normal = Product(file_path="/t/n2.pdf", file_name="n2.pdf", file_size=1, file_hash="n2",
                     text_extracted=True)
    image = Product(file_path="/t/i2.pdf", file_name="i2.pdf", file_size=1, file_hash="i2",
                    is_image_content=True)
    db.add_all([normal, image])
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/queue/text-extraction/queue-all", params={"force": True})
    assert resp.status_code == 200

    assert await _count_text_items(db, normal.id) == 1   # force re-does extracted
    assert await _count_text_items(db, image.id) == 0     # but still skips image-only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/api/test_queue_all_gating.py -v`
Expected: FAIL — image/dead products get queued (counts are 1, not 0).

- [ ] **Step 3: Gate both query branches**

In `backend/grimoire/api/routes/queue.py`, find (inside `queue_all_for_text_extraction`):

```python
    # Find products without text extraction
    if force:
        query = select(Product).order_by(Product.file_size.desc())
    else:
        query = select(Product).where(
            Product.text_extracted == False
        ).order_by(Product.file_size.desc())
```

Replace with:

```python
    # Find products that still need text extraction. Always skip image-only and
    # permanently-unextractable PDFs (even under force) — use the "Retry
    # unextractable" action to reconsider those explicitly.
    skip_flagged = (
        Product.is_image_content == False,
        Product.text_unextractable == False,
    )
    if force:
        query = select(Product).where(*skip_flagged).order_by(Product.file_size.desc())
    else:
        query = select(Product).where(
            Product.text_extracted == False, *skip_flagged
        ).order_by(Product.file_size.desc())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/api/test_queue_all_gating.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/api/routes/queue.py backend/tests/api/test_queue_all_gating.py
git commit -m "feat(api): queue-all skips image-only/unextractable products"
```

---

## Task 4: Gate scanner text-queue, ai_identify, and embed re-queue

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py`
- Modify: `backend/grimoire/services/scanner.py`
- Test: `backend/tests/services/test_disposition_gating.py`

**Context for the tests:** `queue_ai_identify_if_enabled` reads settings via the
module-scope `get_setting(db, key, default)` defined in `queue_processor.py`
(there is NO `set_setting` service — the only setter is the `settings` route).
`queue_ai_identify_if_enabled` returns `False` early if `auto_identify_on_scan`
is off, so a meaningful test must force it on (patch `get_setting`) and provide a
positive control, or it passes vacuously.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_disposition_gating.py`:

```python
"""ai_identify / embed re-queue and the disposition predicate respect the flags."""
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy import select

from grimoire.models.product import Product
from grimoire.models import ProcessingQueue
from grimoire.services.queue_processor import (
    queue_ai_identify_if_enabled,
    _auto_requeue_embeddings,
    is_processing_disposition_blocked,
)


async def _count(db, product_id, task_type):
    res = await db.execute(
        select(ProcessingQueue).where(
            ProcessingQueue.product_id == product_id,
            ProcessingQueue.task_type == task_type,
        )
    )
    return len(list(res.scalars().all()))


def _mk(**kw):
    base = dict(file_size=1)
    base.update(kw)
    return Product(**base)


def test_disposition_predicate():
    assert is_processing_disposition_blocked(_mk(file_path="/a", file_name="a", file_hash="a")) is False
    assert is_processing_disposition_blocked(
        _mk(file_path="/b", file_name="b", file_hash="b", is_image_content=True)) is True
    assert is_processing_disposition_blocked(
        _mk(file_path="/c", file_name="c", file_hash="c", text_unextractable=True)) is True


def _settings_stub(db, key, default=None):
    # Force auto-identify ON with the OpenAI provider (no network needed).
    return {"auto_identify_on_scan": True, "auto_identify_provider": "openai"}.get(key, default)


@pytest.mark.asyncio
async def test_ai_identify_gated_by_disposition(db, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    normal = _mk(file_path="/t/ai_ok.pdf", file_name="ai_ok.pdf", file_hash="aiok", text_extracted=True)
    image = _mk(file_path="/t/ai_i.pdf", file_name="ai_i.pdf", file_hash="aii", text_extracted=True, is_image_content=True)
    dead = _mk(file_path="/t/ai_d.pdf", file_name="ai_d.pdf", file_hash="aid", text_extracted=True, text_unextractable=True)
    notext = _mk(file_path="/t/ai_n.pdf", file_name="ai_n.pdf", file_hash="ain", text_extracted=False)
    db.add_all([normal, image, dead, notext])
    await db.commit()

    with patch("grimoire.services.queue_processor.get_setting", new=AsyncMock(side_effect=_settings_stub)):
        for p in (normal, image, dead, notext):
            await queue_ai_identify_if_enabled(db, p)
    await db.commit()

    assert await _count(db, normal.id, "ai_identify") == 1   # positive control
    assert await _count(db, image.id, "ai_identify") == 0
    assert await _count(db, dead.id, "ai_identify") == 0
    assert await _count(db, notext.id, "ai_identify") == 0


@pytest.mark.asyncio
async def test_auto_requeue_embeddings_skips_unextractable(db):
    normal = _mk(file_path="/t/e_ok.pdf", file_name="e_ok.pdf", file_hash="eok",
                 text_extracted=True, extracted_text_path="/t/e_ok.json")
    dead = _mk(file_path="/t/e_d.pdf", file_name="e_d.pdf", file_hash="edd",
               text_extracted=True, text_unextractable=True, extracted_text_path="/t/e_d.json")
    db.add_all([normal, dead])
    await db.commit()

    # Make a provider "available" deterministically (local model) without network.
    with patch("grimoire.services.embeddings.SENTENCE_TRANSFORMERS_AVAILABLE", True), \
         patch("grimoire.processors.ai_identifier.check_ollama_available", return_value=False), \
         patch("grimoire.processors.ai_identifier.get_ollama_url", new=AsyncMock(return_value=None)), \
         patch("grimoire.processors.ai_identifier.get_setting_from_db", new=AsyncMock(return_value="")):
        await _auto_requeue_embeddings(db)
    await db.commit()

    assert await _count(db, normal.id, "embed") == 1   # positive control
    assert await _count(db, dead.id, "embed") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_disposition_gating.py -v`
Expected: FAIL — `ImportError` for `is_processing_disposition_blocked` (and, once that exists, ai_identify queued for image/dead; embed requeued for dead).

- [ ] **Step 3: Add the disposition predicate and gate `queue_ai_identify_if_enabled`**

In `backend/grimoire/services/queue_processor.py`, add this helper at module scope
(e.g. just above `queue_ai_identify_if_enabled`):

```python
def is_processing_disposition_blocked(product) -> bool:
    """True if a product is image-only or permanently unextractable and must be
    skipped by every text-extraction / AI-identify re-queue path."""
    return bool(
        getattr(product, "is_image_content", False)
        or getattr(product, "text_unextractable", False)
    )
```

Then find (in `queue_ai_identify_if_enabled`):

```python
    # Check if already identified
    if product.ai_identified:
        return False
```

Replace with:

```python
    # Check if already identified
    if product.ai_identified:
        return False

    # AI-identify needs real extracted text and a content-bearing PDF.
    if not product.text_extracted or is_processing_disposition_blocked(product):
        return False
```

- [ ] **Step 4: Gate the embed re-queue**

In `backend/grimoire/services/queue_processor.py`, find (in `_auto_requeue_embeddings`):

```python
    products_query = select(Product).where(
        Product.text_extracted == True,
        Product.extracted_text_path.isnot(None),
    )
```

Replace with:

```python
    products_query = select(Product).where(
        Product.text_extracted == True,
        Product.extracted_text_path.isnot(None),
        Product.text_unextractable == False,
    )
```

- [ ] **Step 5: Gate the scanner text auto-queue**

In `backend/grimoire/services/scanner.py`, find:

```python
        if auto_extract_text and not product.text_extracted:
            if (product.id, "text") not in existing_tasks:
```

Replace with:

```python
        if (
            auto_extract_text
            and not product.text_extracted
            and not product.is_image_content
            and not product.text_unextractable
        ):
            if (product.id, "text") not in existing_tasks:
```

Then, in the SAME loop, find the ai_identify block:

```python
        if auto_identify and product.text_extracted and not product.ai_identified:
            if (product.id, "ai_identify") not in existing_tasks:
```

Replace with:

```python
        if (
            auto_identify
            and product.text_extracted
            and not product.ai_identified
            and not product.is_image_content
            and not product.text_unextractable
        ):
            if (product.id, "ai_identify") not in existing_tasks:
```

- [ ] **Step 6: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_disposition_gating.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/services/queue_processor.py backend/grimoire/services/scanner.py backend/tests/services/test_disposition_gating.py
git commit -m "feat(services): gate ai_identify/embed/scan re-queue on disposition flags"
```

---

## Task 5: Flag permanent no-text in the handlers

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py`
- Test: `backend/tests/services/test_handler_flagging.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_handler_flagging.py`:

```python
"""OCR handler flags permanent no-text; transient tooling gaps do not flag."""
import pytest
from unittest.mock import patch
from grimoire.models.product import Product
from grimoire.services.queue_processor import handle_ocr_text_task, TaskError


@pytest.mark.asyncio
async def test_ocr_empty_flags_unextractable(db, tmp_path):
    pdf = tmp_path / "img.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    product = Product(file_path=str(pdf), file_name="img.pdf", file_size=1, file_hash="oc1")
    db.add(product)
    await db.commit()

    with patch("grimoire.services.queue_processor.extract_with_ocr", return_value="   "), \
         patch("grimoire.services.queue_processor.TESSERACT_AVAILABLE", True):
        with pytest.raises(TaskError):
            await handle_ocr_text_task(db, product)

    await db.refresh(product)
    assert product.text_unextractable is True
    assert product.extraction_error


@pytest.mark.asyncio
async def test_ocr_unavailable_does_not_flag(db, tmp_path):
    pdf = tmp_path / "img2.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    product = Product(file_path=str(pdf), file_name="img2.pdf", file_size=1, file_hash="oc2")
    db.add(product)
    await db.commit()

    with patch("grimoire.services.queue_processor.TESSERACT_AVAILABLE", False):
        result = await handle_ocr_text_task(db, product)

    assert result is False
    await db.refresh(product)
    assert not product.text_unextractable
```

Note: `handle_ocr_text_task` currently imports `extract_with_ocr` and `TESSERACT_AVAILABLE` *inside* the function. Step 3 hoists those imports to the module top so the test can patch them at `grimoire.services.queue_processor.<name>`.

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_handler_flagging.py -v`
Expected: FAIL — patch targets don't exist at module scope yet, and empty OCR does not currently flag.

- [ ] **Step 3: Add the module constant and hoist OCR imports**

In `backend/grimoire/services/queue_processor.py`, near the top-level constants (just after `PROCESSING_PAUSED_KEY = "processing_paused"`), add:

```python
# Below this many non-whitespace chars, an OCR result counts as "no text".
MIN_EXTRACTED_CHARS = 20
```

Then add a module-level import so the handler and tests share one binding. Near the other top-of-file imports, add:

```python
from grimoire.processors.text_extractor import extract_with_ocr, TESSERACT_AVAILABLE
```

In `handle_ocr_text_task`, DELETE its now-duplicate local import line:

```python
    from grimoire.processors.text_extractor import extract_with_ocr, TESSERACT_AVAILABLE
```

- [ ] **Step 4: Flag empty OCR results (and let `TaskError` propagate)**

`handle_ocr_text_task` wraps its body in `try: ... except Exception: return
False`, which would swallow a raised `TaskError`. Two edits:

First, in `handle_ocr_text_task`, find:

```python
        # OCR is extremely CPU-heavy — must run in thread
        markdown_text = await asyncio.to_thread(
            extract_with_ocr, pdf_path, dpi=200, lang="eng"
        )
```

Insert immediately after it:

```python
        if len((markdown_text or "").strip()) < MIN_EXTRACTED_CHARS:
            product.text_unextractable = True
            product.extraction_error = "no text after ocr"
            await db.commit()
            raise TaskError(
                f"Product {product.id} '{product.file_name}': no text after OCR"
            )
```

Second, in the same function, find the exception handler:

```python
    except Exception as e:
        logger.error(f"OCR extraction failed for product {product.id}: {e}")
        return False
```

Replace with (re-raise `TaskError` so it is treated as a permanent failure, not a
swallowed retry):

```python
    except TaskError:
        raise
    except Exception as e:
        logger.error(f"OCR extraction failed for product {product.id}: {e}")
        return False
```

- [ ] **Step 5: Flag corrupt/encrypted PDFs in the text handler**

In `handle_text_task`, find:

```python
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
```

Replace with:

```python
    # Run sync extraction in thread pool
    success = await asyncio.to_thread(process_text_extraction_sync, product, False)
    if success:
        await db.commit()
        # Also update the FTS index
        await update_search_vector(db, product)
        # Queue AI identification if enabled
        await queue_ai_identify_if_enabled(db, product)
        await db.commit()
        return True

    # Extraction failed. A missing file is transient — retry, do not flag.
    if not pdf_path.exists():
        return False

    # Diagnose whether the PDF is permanently unextractable (encrypted/corrupt)
    # vs a transient error we should retry.
    reason = await asyncio.to_thread(_diagnose_pdf_unextractable, str(pdf_path))
    if reason:
        product.text_unextractable = True
        product.extraction_error = reason
        await db.commit()
        raise TaskError(f"Product {product.id} '{product.file_name}': {reason}")
    return False
```

(`handle_text_task` has no wrapping `try/except`, so the `TaskError` propagates
to `_process_item_with_session`, which marks it failed without retry.)

Then add this helper at module scope in `queue_processor.py` (e.g. just above `handle_text_task`):

```python
def _diagnose_pdf_unextractable(path: str) -> str | None:
    """Return a permanent-failure reason if the PDF can't be opened/decrypted,
    else None (treat as transient and retry). Runs in a worker thread."""
    import fitz
    try:
        doc = fitz.open(path)
    except Exception:
        return "corrupt pdf"
    try:
        if doc.is_encrypted and not doc.authenticate(""):
            return "encrypted"
    finally:
        doc.close()
    return None
```

- [ ] **Step 6: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_handler_flagging.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Import sanity + commit**

Run: `cd backend && PYTHONPATH=. .venv/Scripts/python.exe -c "import grimoire.services.queue_processor; print('ok')"`
Expected: `ok`.

```bash
git add backend/grimoire/services/queue_processor.py backend/tests/services/test_handler_flagging.py
git commit -m "feat(worker): flag encrypted/corrupt/no-text-after-OCR as unextractable"
```

---

## Task 6: Reclassify-failures endpoint (one-time cleanup)

**Files:**
- Modify: `backend/grimoire/api/routes/queue.py`
- Test: `backend/tests/api/test_reclassify_failures.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/test_reclassify_failures.py`:

```python
"""POST /queue/reclassify-failures flags permanent no-text failures, keeps transient."""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from grimoire.main import app
from grimoire.database import get_db
from grimoire.models.product import Product
from grimoire.models import ProcessingQueue


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reclassify_flags_permanent_keeps_transient(client, db):
    perm = Product(file_path="/t/p.pdf", file_name="p.pdf", file_size=1, file_hash="rp")
    trans = Product(file_path="/t/t.pdf", file_name="t.pdf", file_size=1, file_hash="rt")
    img = Product(file_path="/t/g.pdf", file_name="g.pdf", file_size=1, file_hash="rg",
                  is_image_content=True)
    db.add_all([perm, trans, img])
    await db.commit()

    db.add_all([
        ProcessingQueue(product_id=perm.id, task_type="ocr_text", status="failed",
                        error_message="no text after ocr"),
        ProcessingQueue(product_id=trans.id, task_type="text", status="failed",
                        error_message="tesseract not installed"),
        ProcessingQueue(product_id=img.id, task_type="text", status="failed",
                        error_message="whatever"),
    ])
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/queue/reclassify-failures")
    assert resp.status_code == 200
    body = resp.json()
    assert body["flagged"] >= 1
    assert body["cleared"] >= 2      # perm + img failed items removed
    assert body["left_retryable"] >= 1

    await db.refresh(perm)
    await db.refresh(trans)
    assert perm.text_unextractable is True

    # transient failed item remains
    remaining = await db.execute(
        select(ProcessingQueue).where(ProcessingQueue.product_id == trans.id)
    )
    assert len(list(remaining.scalars().all())) == 1

    # second run is a no-op (idempotent)
    async with client as c:
        resp2 = await c.post("/api/v1/queue/reclassify-failures")
    assert resp2.json()["cleared"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/api/test_reclassify_failures.py -v`
Expected: FAIL — 404 (endpoint missing).

- [ ] **Step 3: Add the endpoint**

In `backend/grimoire/api/routes/queue.py`, add this endpoint (place it near the other `text-extraction` routes):

```python
@router.post("/reclassify-failures")
async def reclassify_failures(db: DbSession) -> dict:
    """One-time cleanup: flag image-only / permanently-unextractable products and
    remove their dead failed items; leave transient/provider failures retryable."""
    from grimoire.services.extraction_classifier import classify_extraction_failure

    result = await db.execute(
        select(ProcessingQueue).where(
            ProcessingQueue.status == "failed",
            ProcessingQueue.task_type.in_(["text", "ocr_text", "ai_identify"]),
        )
    )
    items = list(result.scalars().all())

    product_ids = {item.product_id for item in items}
    products: dict[int, Product] = {}
    if product_ids:
        prod_result = await db.execute(select(Product).where(Product.id.in_(product_ids)))
        products = {p.id: p for p in prod_result.scalars().all()}

    flagged = 0
    cleared = 0
    left_retryable = 0

    for item in items:
        product = products.get(item.product_id)
        if product is None:
            await db.delete(item)
            cleared += 1
            continue

        permanent = (
            product.is_image_content
            or product.text_unextractable
            or classify_extraction_failure(item.error_message) == "permanent"
        )

        # ai_identify on a product with no usable text can never succeed.
        ai_dead = item.task_type == "ai_identify" and (
            not product.text_extracted
            or product.is_image_content
            or product.text_unextractable
        )

        if permanent and item.task_type in ("text", "ocr_text"):
            if not product.is_image_content and not product.text_unextractable:
                product.text_unextractable = True
                product.extraction_error = (
                    item.error_message or "unextractable"
                )[:500]
                flagged += 1
            await db.delete(item)
            cleared += 1
        elif ai_dead:
            await db.delete(item)
            cleared += 1
        else:
            left_retryable += 1

    await db.commit()
    return {"flagged": flagged, "cleared": cleared, "left_retryable": left_retryable}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/api/test_reclassify_failures.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/api/routes/queue.py backend/tests/api/test_reclassify_failures.py
git commit -m "feat(api): reclassify-failures cleanup endpoint"
```

---

## Task 7: Retry-unextractable endpoint

**Files:**
- Modify: `backend/grimoire/api/routes/queue.py`
- Test: `backend/tests/api/test_retry_unextractable.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/test_retry_unextractable.py`:

```python
"""POST /queue/text-extraction/retry-unextractable clears flags and re-queues."""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from grimoire.main import app
from grimoire.database import get_db
from grimoire.models.product import Product
from grimoire.models import ProcessingQueue


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_retry_unextractable(client, db):
    dead = Product(file_path="/t/u.pdf", file_name="u.pdf", file_size=1, file_hash="ru",
                   text_unextractable=True, extraction_error="no text after ocr")
    ok = Product(file_path="/t/o.pdf", file_name="o.pdf", file_size=1, file_hash="ro")
    db.add_all([dead, ok])
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/queue/text-extraction/retry-unextractable")
    assert resp.status_code == 200
    assert resp.json()["requeued"] == 1

    await db.refresh(dead)
    assert dead.text_unextractable is False
    assert dead.extraction_error is None

    items = await db.execute(
        select(ProcessingQueue).where(
            ProcessingQueue.product_id == dead.id, ProcessingQueue.task_type == "text"
        )
    )
    assert len(list(items.scalars().all())) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/api/test_retry_unextractable.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Add the endpoint**

In `backend/grimoire/api/routes/queue.py`, add:

```python
@router.post("/text-extraction/retry-unextractable")
async def retry_unextractable(db: DbSession) -> dict:
    """Clear the text_unextractable flag and re-queue those products for text
    extraction — the explicit override for when extraction quality improves."""
    result = await db.execute(
        select(Product).where(Product.text_unextractable == True)
    )
    products = list(result.scalars().all())

    requeued = 0
    for product in products:
        product.text_unextractable = False
        product.extraction_error = None

        existing = await db.execute(
            select(ProcessingQueue).where(
                ProcessingQueue.product_id == product.id,
                ProcessingQueue.task_type == "text",
                ProcessingQueue.status.in_(["pending", "processing"]),
            )
        )
        if existing.scalar_one_or_none():
            continue
        db.add(ProcessingQueue(
            product_id=product.id, task_type="text", priority=5, status="pending",
        ))
        requeued += 1

    await db.commit()
    return {"requeued": requeued, "cleared_flags": len(products)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/api/test_retry_unextractable.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/api/routes/queue.py backend/tests/api/test_retry_unextractable.py
git commit -m "feat(api): retry-unextractable override endpoint"
```

---

## Task 8: Expose flagged counts in library stats

**Files:**
- Modify: `backend/grimoire/api/routes/library.py`
- Test: `backend/tests/api/test_library_stats_disposition.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/test_library_stats_disposition.py`:

```python
"""library/stats reports image_content + unextractable counts."""
import pytest
from httpx import AsyncClient, ASGITransport

from grimoire.main import app
from grimoire.database import get_db
from grimoire.models.product import Product


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stats_reports_disposition_counts(client, db):
    db.add_all([
        Product(file_path="/t/si.pdf", file_name="si.pdf", file_size=1, file_hash="si",
                is_image_content=True),
        Product(file_path="/t/su.pdf", file_name="su.pdf", file_size=1, file_hash="su",
                text_unextractable=True),
    ])
    await db.commit()

    async with client as c:
        resp = await c.get("/api/v1/library/stats")
    assert resp.status_code == 200
    proc = resp.json()["processing"]
    assert proc["image_content"] >= 1
    assert proc["unextractable"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/api/test_library_stats_disposition.py -v`
Expected: FAIL — `KeyError`/assert (keys absent).

- [ ] **Step 3: Add the counts**

In `backend/grimoire/api/routes/library.py`, find:

```python
    ai_query = select(func.count(Product.id)).where(Product.ai_identified == True)
    ai_result = await db.execute(ai_query)
    ai_identified = ai_result.scalar() or 0
```

Insert immediately after it:

```python
    image_content_query = select(func.count(Product.id)).where(Product.is_image_content == True)
    image_content = (await db.execute(image_content_query)).scalar() or 0

    unextractable_query = select(func.count(Product.id)).where(Product.text_unextractable == True)
    unextractable = (await db.execute(unextractable_query)).scalar() or 0
```

Then find:

```python
        "processing": {
            "covers_extracted": covers_extracted,
            "text_extracted": text_extracted,
            "ai_identified": ai_identified,
            "ai_identify_failed": ai_identify_failed,
        },
```

Replace with:

```python
        "processing": {
            "covers_extracted": covers_extracted,
            "text_extracted": text_extracted,
            "ai_identified": ai_identified,
            "ai_identify_failed": ai_identify_failed,
            "image_content": image_content,
            "unextractable": unextractable,
        },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/api/test_library_stats_disposition.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/api/routes/library.py backend/tests/api/test_library_stats_disposition.py
git commit -m "feat(api): expose image_content + unextractable counts in library stats"
```

---

## Task 9: Frontend — disposition summary + buttons

**Files:**
- Modify: `frontend/src/pages/LibraryManagement.tsx`

- [ ] **Step 1: Extend the LibraryStats type**

In `frontend/src/pages/LibraryManagement.tsx`, find:

```tsx
  processing: {
    covers_extracted: number;
    text_extracted: number;
    ai_identified: number;
    ai_identify_failed?: number;
  };
```

Replace with:

```tsx
  processing: {
    covers_extracted: number;
    text_extracted: number;
    ai_identified: number;
    ai_identify_failed?: number;
    image_content?: number;
    unextractable?: number;
  };
```

- [ ] **Step 2: Add the two mutations**

In `frontend/src/pages/LibraryManagement.tsx`, find the `forceReextractAllMutation` block (added earlier) and insert immediately after it:

```tsx
  const reclassifyFailuresMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/queue/reclassify-failures');
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-management-stats'] });
      queryClient.invalidateQueries({ queryKey: ['text-extraction-stats'] });
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
    },
  });

  const retryUnextractableMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/queue/text-extraction/retry-unextractable');
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-management-stats'] });
      queryClient.invalidateQueries({ queryKey: ['text-extraction-stats'] });
    },
  });
```

- [ ] **Step 3: Add the summary + buttons in the Text Extraction card**

In `frontend/src/pages/LibraryManagement.tsx`, find the progress-bar block inside the Text Extraction section:

```tsx
              <div className="mt-4">
                <div className="h-2 rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
                  <div
                    className="h-2 rounded-full bg-blue-500 transition-all"
                    style={{
                      width: `${(stats.processing.text_extracted / stats.total_products) * 100}%`,
                    }}
                  />
                </div>
              </div>
```

Insert immediately after that closing `</div>`:

```tsx
              {((stats.processing.image_content ?? 0) > 0 || (stats.processing.unextractable ?? 0) > 0) && (
                <div className="mt-4 flex items-center justify-between rounded-md p-3" style={{ backgroundColor: 'var(--color-surface-raised)' }}>
                  <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                    {stats.processing.image_content ?? 0} image collections · {stats.processing.unextractable ?? 0} unextractable — excluded from extraction
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => reclassifyFailuresMutation.mutate()}
                      disabled={reclassifyFailuresMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-md border px-3 text-sm font-medium disabled:opacity-50"
                      style={{ minHeight: '40px', borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)', backgroundColor: 'var(--color-surface)' }}
                      title="Classify existing failed items: flag image-only/unextractable, keep transient failures retryable"
                    >
                      {reclassifyFailuresMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Filter className="h-4 w-4" />}
                      Reclassify failed queue
                    </button>
                    {(stats.processing.unextractable ?? 0) > 0 && (
                      <button
                        onClick={() => retryUnextractableMutation.mutate()}
                        disabled={retryUnextractableMutation.isPending}
                        className="inline-flex items-center gap-2 rounded-md border px-3 text-sm font-medium disabled:opacity-50"
                        style={{ minHeight: '40px', borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)', backgroundColor: 'var(--color-surface)' }}
                        title="Clear the unextractable flag and re-queue those PDFs for extraction"
                      >
                        {retryUnextractableMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                        Retry unextractable
                      </button>
                    )}
                  </div>
                </div>
              )}
```

(`Loader2`, `Filter`, and `RefreshCw` are already imported in this file.)

- [ ] **Step 4: Verify the build**

Run (from `frontend/`): `npx tsc -b`
Expected: only the pre-existing `Settings.tsx` `Shield` error; no errors in `LibraryManagement.tsx`.
Then: `npx eslint src/pages/LibraryManagement.tsx` → no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LibraryManagement.tsx
git commit -m "feat(frontend): disposition summary + reclassify/retry-unextractable buttons"
```

---

## Task 10: Full verification

- [ ] **Step 1: Full backend suite**

Run (from `backend/`): `C:/Users/mkemi/miniconda3/python.exe -m pytest -q`
Expected: the **6 pre-existing failures only** (diagnostics ×2, products-list ×1, scanner-batch ×1, backup-routes ×2), plus all new tests passing. No *new* failures.

- [ ] **Step 2: Frontend gate**

Run (from `frontend/`): `npx tsc -b`
Expected: only the pre-existing `Settings.tsx` `Shield` error.

- [ ] **Step 3: Manual end-to-end (requires the running app)**

With the stack running (backend + queue worker + `npm run dev`):
1. Processing tab shows "N image collections · M unextractable — excluded from extraction" once any exist.
2. **Reclassify failed queue** → the failed count drops (image/no-text cleared), transient/provider failures remain; unextractable count rises.
3. **Re-extract All (force)** no longer re-queues the flagged image-only PDFs (queue `text` count for them stays 0).
4. **Retry unextractable** clears the flags and re-queues those PDFs.
5. Resume processing and confirm image-only PDFs are not re-failing.

- [ ] **Step 4: Confirm clean tree**

Run: `git status` — only intended commits; no stray unrelated modifications.

---

## Follow-ups (separate, not this plan)

- Embed 400 hardening: send chunks to Ollama `/api/embed` in smaller sub-batches; after a persistent 400, flag the product embed-skipped.
- Smarter detection heuristics for `detect_image_content` / `detect_needs_ocr`.
