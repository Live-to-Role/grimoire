# Document Processing Performance Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modernize Grimoire's PDF processing pipeline with techniques and libraries released after the project's creation, cutting library-scan time and improving extraction quality without changing external behavior.

**Architecture:** Eight independent, incrementally-committable tasks against the existing pipeline: render covers at target resolution instead of fixed 2×; reorder OCR detection ahead of full extraction; batch Ollama embedding requests; normalize/batch local embeddings; add `pymupdf4llm` as the preferred markdown extractor; add PyMuPDF's integrated Tesseract OCR (dropping the poppler subprocess path to a fallback); dedupe gallery images by content hash; bump Docker to Python 3.12. No schema changes, no API changes.

**Tech Stack:** Python 3.12, PyMuPDF (fitz) ≥1.23, pymupdf4llm (new dep), Pillow, pytest + pytest-asyncio, httpx (with MockTransport for tests), sentence-transformers, Huey.

---

## Context for a zero-context engineer

- Backend lives in `backend/`; run all commands from `backend/` with the venv at `backend/.venv` activated (`backend\.venv\Scripts\activate` on Windows).
- Tests: `cd backend && python -m pytest tests/ -v`. The suite must stay green after every task. `tests/conftest.py` provides a session-scoped in-memory SQLite `db` fixture — committed data persists across tests in the same session.
- The processing flow: `services/scanner.py` finds PDFs → rows in `ProcessingQueue` → `services/queue_processor.py` handlers call into `services/processor.py` and `processors/*.py`. Everything in this plan is below the queue layer, so no queue/DB changes are needed.
- Nothing downstream parses the `## Page N` markers in extracted markdown (verified by grep — only the extractors emit them). Output format changes are safe.
- `fitz` is the import name for PyMuPDF.

## Out of scope (deliberately)

- **sqlite-vec vector search** — architectural change to semantic search; needs its own design spec and migration plan.
- **model2vec static embeddings** — new provider option, separate feature decision.
- **pdfplumber double-pass footer detection** — becomes dead-path once pymupdf4llm is the primary extractor (Task 5); not worth optimizing a fallback.
- **Parallel queue item processing** — SQLite single-writer lock makes gains marginal; revisit after backup-system work lands.

---

## Task 0: Shared test fixtures for generated PDFs

**Files:**
- Create: `backend/tests/pdf_fixtures.py`
- Modify: `backend/tests/conftest.py` (add import/re-export)

The processing tests need real PDFs. We generate them with PyMuPDF at test time — no binary fixtures in git.

- [ ] **Step 1: Create the fixture module**

Create `backend/tests/pdf_fixtures.py`:

```python
"""Generated-PDF fixtures for document processing tests."""

import fitz
import pytest
from PIL import Image


@pytest.fixture
def text_pdf(tmp_path):
    """A one-page text-based PDF (US Letter)."""
    pdf_path = tmp_path / "text.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Grimoire Test Document", fontsize=24)
    page.insert_text(
        (72, 144),
        "Some body text for extraction verification purposes.",
        fontsize=12,
    )
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def scanned_pdf(tmp_path):
    """A one-page image-only PDF (no text layer) — simulates a scan.

    The image is rendered from a text page so OCR tests have real
    glyphs to recognize.
    """
    # Render a text page to an image
    src = fitz.open()
    src_page = src.new_page(width=612, height=792)
    src_page.insert_text((72, 200), "GRIMOIRE OCR SAMPLE", fontsize=36)
    pix = src_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    img_path = tmp_path / "page.png"
    pix.save(str(img_path))
    src.close()

    # Build a PDF whose only content is that image
    pdf_path = tmp_path / "scanned.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(page.rect, filename=str(img_path))
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def repeated_image_pdf(tmp_path):
    """A three-page PDF with the identical image on every page."""
    img = Image.new("RGB", (400, 400), (180, 40, 40))
    img_path = tmp_path / "art.png"
    img.save(img_path)

    pdf_path = tmp_path / "repeated.pdf"
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page(width=612, height=792)
        page.insert_image(fitz.Rect(100, 100, 500, 500), filename=str(img_path))
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path
```

- [ ] **Step 2: Register fixtures in conftest**

In `backend/tests/conftest.py`, add at the end of the imports section:

```python
from tests.pdf_fixtures import (  # noqa: F401
    repeated_image_pdf,
    scanned_pdf,
    text_pdf,
)
```

If the existing conftest imports use a different path style (e.g. bare `from pdf_fixtures import ...` because `tests/` is the rootdir), match the existing style. Check how conftest currently imports things and follow it.

- [ ] **Step 3: Verify fixtures load**

Run: `cd backend && python -m pytest tests/ --collect-only -q 2>&1 | tail -5`
Expected: existing tests collected, no import errors.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/pdf_fixtures.py backend/tests/conftest.py
git commit -m "test: add generated-PDF fixtures for processing tests"
```

---

## Task 1: Render covers at target resolution (~16× fewer pixels)

**Files:**
- Modify: `backend/grimoire/services/processor.py:30-65` (`extract_cover_image`)
- Test: `backend/tests/test_cover_extraction.py` (create)

**Problem:** `extract_cover_image` renders page 1 at fixed `zoom=2.0` (~1224×1584 px for a letter page), then thumbnails down to a 300×400 box. Rendering cost scales with pixel count. Computing the zoom from the target size renders ~16× fewer pixels. This runs for **every PDF** during a library scan — it is the hottest single operation in the pipeline.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_cover_extraction.py`:

```python
"""Tests for cover extraction render scaling."""

import pytest
from PIL import Image

from grimoire.services.processor import _cover_scale, extract_cover_image


def test_cover_scale_letter_page_renders_near_target():
    # 612x792pt letter page, 300px target -> scale ~0.61, far below old 2.0
    scale = _cover_scale(612, 792, 300)
    expected = min(300 / 612, 400 / 792) * 1.25
    assert scale == pytest.approx(expected)
    assert scale < 1.0


def test_cover_scale_tiny_page_capped_at_two():
    # A tiny page must not be upscaled past the old 2.0 behavior
    assert _cover_scale(100, 100, 300) == 2.0


def test_cover_scale_degenerate_page_returns_safe_default():
    assert _cover_scale(0, 0, 300) == 1.0


def test_extract_cover_image_output_fits_target_box(text_pdf, tmp_path):
    out = tmp_path / "cover.jpg"
    assert extract_cover_image(text_pdf, out, size=300) is True
    with Image.open(out) as img:
        assert img.width <= 300
        assert img.height <= 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_cover_extraction.py -v`
Expected: FAIL — `ImportError: cannot import name '_cover_scale'`

- [ ] **Step 3: Implement `_cover_scale` and use it**

In `backend/grimoire/services/processor.py`, add above `extract_cover_image`:

```python
def _cover_scale(page_width: float, page_height: float, size: int) -> float:
    """Render scale so the pixmap is ~1.25x the final thumbnail box.

    Rendering at fixed 2x wastes ~16x the pixels for a letter page;
    the 1.25 factor leaves headroom for a quality LANCZOS downscale.
    Capped at 2.0 so tiny pages never render larger than before.
    """
    if page_width <= 0 or page_height <= 0:
        return 1.0
    box_w, box_h = size, size * 4 // 3
    scale = min(box_w / page_width, box_h / page_height) * 1.25
    return min(scale, 2.0)
```

Then in `extract_cover_image`, replace:

```python
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
```

with:

```python
        zoom = _cover_scale(page.rect.width, page.rect.height, size)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
```

The existing `img.thumbnail((size, size * 4 // 3), ...)` line stays — it performs the final exact fit.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_cover_extraction.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Run full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all pass (55+ tests)

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/services/processor.py backend/tests/test_cover_extraction.py
git commit -m "perf(covers): render cover pixmap at target size instead of fixed 2x"
```

---

## Task 2: Fast page counts + OCR detection before full extraction

**Files:**
- Modify: `backend/grimoire/processors/text_extractor.py:605-690` (`extract_text_to_markdown`), `:895-993` (`extract_text_with_ocr_fallback`)
- Test: `backend/tests/test_text_extraction_flow.py` (create)

**Problem A:** `extract_text_to_markdown` opens the PDF with pdfplumber (slow — pdfminer parses the full document) *just to count pages*, then re-opens it with PyMuPDF. `extract_text_with_ocr_fallback` repeats this pdfplumber open two more times.

**Problem B:** `extract_text_with_ocr_fallback` runs the **entire** standard extraction first, then calls `detect_needs_ocr` (which re-opens the doc), and if OCR is needed, throws the standard result away. The cheap 3-page detection must run first.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_text_extraction_flow.py`:

```python
"""Tests for extraction flow ordering and page counting."""

import pytest

from grimoire.processors import text_extractor
from grimoire.processors.text_extractor import (
    _get_page_count,
    extract_text_with_ocr_fallback,
)


def test_get_page_count(text_pdf):
    assert _get_page_count(text_pdf) == 1


def test_ocr_fallback_skips_ocr_for_text_pdf(text_pdf):
    result = extract_text_with_ocr_fallback(text_pdf)
    assert result["ocr_used"] is False
    assert "Grimoire Test Document" in result["markdown"]


def test_ocr_path_never_runs_standard_extraction(scanned_pdf, monkeypatch):
    """When detection says OCR, standard extraction must not run at all."""
    std_calls = []
    monkeypatch.setattr(
        text_extractor,
        "extract_text_to_markdown",
        lambda *a, **k: std_calls.append(1) or {"markdown": "", "total_pages": 1},
    )
    monkeypatch.setattr(
        text_extractor,
        "extract_with_ocr",
        lambda *a, **k: "## Page 1\n\nOCR TEXT\n\n",
    )
    monkeypatch.setattr(text_extractor, "TESSERACT_AVAILABLE", True)

    result = extract_text_with_ocr_fallback(scanned_pdf)

    assert result["ocr_used"] is True
    assert std_calls == []


def test_ocr_failure_falls_back_to_standard_extraction(scanned_pdf, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("tesseract exploded")

    monkeypatch.setattr(text_extractor, "extract_with_ocr", boom)
    monkeypatch.setattr(text_extractor, "TESSERACT_AVAILABLE", True)

    result = extract_text_with_ocr_fallback(scanned_pdf)

    assert result["ocr_used"] is False
    assert "OCR attempted but failed" in result["ocr_reason"]
    assert "markdown" in result  # standard extraction ran as fallback
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_text_extraction_flow.py -v`
Expected: FAIL — `ImportError: cannot import name '_get_page_count'`

- [ ] **Step 3: Add `_get_page_count` helper**

In `backend/grimoire/processors/text_extractor.py`, add above `extract_text_to_markdown`:

```python
def _get_page_count(pdf_path: str | Path) -> int:
    """Count pages cheaply. PyMuPDF only reads the xref table;
    pdfplumber (pdfminer) parses the whole document just to count."""
    if PYMUPDF_AVAILABLE:
        doc = fitz.open(str(pdf_path))
        try:
            return len(doc)
        finally:
            doc.close()
    with pdfplumber.open(str(pdf_path)) as pdf:
        return len(pdf.pages)
```

In `extract_text_to_markdown`, replace:

```python
    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)
```

with:

```python
    total_pages = _get_page_count(pdf_path)
```

- [ ] **Step 4: Reorder `extract_text_with_ocr_fallback`**

Replace the entire body of `extract_text_with_ocr_fallback` **after** the `force_ocr` block (i.e. from `# First try standard extraction` down to the final `return result`) with:

```python
    # Detect FIRST (cheap: samples 3 pages) so image-based PDFs never
    # pay for a full standard extraction that gets thrown away.
    detection = detect_needs_ocr(pdf_path)

    if detection["needs_ocr"] and TESSERACT_AVAILABLE:
        try:
            total_pages = _get_page_count(pdf_path)
            if end_page is None:
                end_page = total_pages

            markdown_text = extract_with_ocr(pdf_path, start_page, end_page, ocr_dpi, ocr_lang)

            return {
                "markdown": markdown_text,
                "total_pages": total_pages,
                "pages_extracted": f"{start_page}-{end_page}",
                "method": "tesseract_ocr",
                "char_count": len(markdown_text),
                "ocr_used": True,
                "ocr_reason": detection["reason"],
            }
        except Exception as e:
            result = extract_text_to_markdown(pdf_path, start_page, end_page, **kwargs)
            if "error" in result:
                return result
            result["ocr_used"] = False
            result["ocr_reason"] = f"OCR attempted but failed: {e}"
            return result

    result = extract_text_to_markdown(pdf_path, start_page, end_page, **kwargs)
    if "error" in result:
        return result

    result["ocr_used"] = False
    if detection["needs_ocr"]:
        result["ocr_reason"] = (
            f"OCR needed ({detection['reason']}) but pytesseract not available"
        )
        result["needs_ocr"] = True
    else:
        result["ocr_reason"] = detection["reason"]
    return result
```

Also update the two `with pdfplumber.open(...)` page-count blocks inside the `force_ocr` branch to use `_get_page_count(pdf_path)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_text_extraction_flow.py -v`
Expected: 4 PASSED

- [ ] **Step 6: Run full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/processors/text_extractor.py backend/tests/test_text_extraction_flow.py
git commit -m "perf(extraction): cheap page counts, OCR detection before full extraction"
```

---

## Task 3: Batch Ollama embedding requests

**Files:**
- Modify: `backend/grimoire/services/embeddings.py:94-116` (`embed_with_ollama`)
- Test: `backend/tests/test_embeddings.py` (create; Task 4 adds to it)

**Problem:** One HTTP POST per text chunk. Ollama's `/api/embed` (the endpoint already used) accepts a list in `input` and returns all vectors in one response. A 200-chunk book goes from 200 round trips to 1.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_embeddings.py`:

```python
"""Tests for embedding generation and similarity search."""

import json

import httpx
import pytest

from grimoire.services import embeddings as emb_mod
from grimoire.services.embeddings import embed_with_ollama


@pytest.mark.asyncio
async def test_ollama_embeds_batch_in_single_request(monkeypatch):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests_seen.append(payload)
        n = len(payload["input"])
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]] * n})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    results = await embed_with_ollama(["a", "b", "c"], "http://fake:11434")

    assert len(requests_seen) == 1, "must be a single batched request"
    assert requests_seen[0]["input"] == ["a", "b", "c"]
    assert len(results) == 3
    assert results[0].embedding == [0.1, 0.2, 0.3]
```

Note: if the project's pytest-asyncio is in strict mode without markers configured, check `backend/pyproject.toml` / `pytest.ini` for `asyncio_mode`. Existing async tests in `backend/tests/` show the convention — follow it.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_embeddings.py -v`
Expected: FAIL — `requests_seen` has 3 entries (current code loops per text)

- [ ] **Step 3: Implement batched request**

In `backend/grimoire/services/embeddings.py`, replace the body of `embed_with_ollama`:

```python
async def embed_with_ollama(
    texts: list[str],
    base_url: str,
    model: str = "nomic-embed-text",
) -> list[EmbeddingResult]:
    """Generate embeddings using Ollama API (single batched request).

    /api/embed accepts a list input (Ollama >= 0.2.6, July 2024) and
    returns all vectors at once — one round trip instead of len(texts).
    """
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/api/embed",
            json={
                "model": model,
                "input": texts,
            },
        )
        response.raise_for_status()
        data = response.json()

    return [
        EmbeddingResult(embedding=emb, model=model)
        for emb in data["embeddings"]
    ]
```

(Timeout raised 120→300s because one request now covers the whole batch.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_embeddings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/embeddings.py backend/tests/test_embeddings.py
git commit -m "perf(embeddings): batch Ollama requests into single /api/embed call"
```

---

## Task 4: Normalize local embeddings, delegate `find_similar` to batch numpy path

**Files:**
- Modify: `backend/grimoire/services/embeddings.py:74-91` (`embed_with_local`), `:192-217` (`find_similar`)
- Test: `backend/tests/test_embeddings.py` (extend)

**Problem A:** `embed_with_local` calls `model.encode(texts)` without `normalize_embeddings=True` or an explicit `batch_size`. Normalized vectors make cosine similarity a bare dot product (and cosine is scale-invariant, so mixing with older unnormalized stored vectors changes nothing).

**Problem B:** `find_similar` builds two numpy arrays **per comparison** in a Python loop, while `search_product_vectors` (same file) already does the whole thing as one matrix operation. Delegate.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_embeddings.py`:

```python
from grimoire.services.embeddings import find_similar


def test_find_similar_ranks_by_cosine():
    query = [1.0, 0.0]
    embs = [
        (1, [1.0, 0.0]),   # identical -> 1.0
        (2, [0.0, 1.0]),   # orthogonal -> 0.0
        (3, [0.7, 0.7]),   # 45 degrees -> ~0.707
    ]
    results = find_similar(query, embs, top_k=2)
    assert [pid for pid, _ in results] == [1, 3]
    assert results[0][1] == pytest.approx(1.0)
    assert results[1][1] == pytest.approx(0.7071, abs=1e-3)


def test_find_similar_respects_threshold():
    query = [1.0, 0.0]
    embs = [(1, [1.0, 0.0]), (2, [0.0, 1.0])]
    results = find_similar(query, embs, threshold=0.5)
    assert [pid for pid, _ in results] == [1]


def test_find_similar_skips_mismatched_dimensions():
    query = [1.0, 0.0]
    embs = [(1, [1.0, 0.0]), (2, [1.0, 0.0, 0.0])]  # 3-dim ignored
    results = find_similar(query, embs)
    assert [pid for pid, _ in results] == [1]


def test_find_similar_empty_input():
    assert find_similar([1.0, 0.0], []) == []
```

- [ ] **Step 2: Run tests to verify current state**

Run: `cd backend && python -m pytest tests/test_embeddings.py -v`
Expected: `test_find_similar_skips_mismatched_dimensions` FAILS (current per-pair loop crashes or mis-scores on dimension mismatch); the other three may pass — that is fine, they are characterization tests locking in behavior before the refactor.

- [ ] **Step 3: Rewrite `find_similar` as a delegation**

In `backend/grimoire/services/embeddings.py`, replace the body of `find_similar` (keep the docstring):

```python
def find_similar(
    query_embedding: list[float],
    embeddings: list[tuple[int, list[float]]],  # List of (id, embedding)
    top_k: int = 10,
    threshold: float = 0.0,
) -> list[tuple[int, float]]:
    """
    Find most similar items to a query embedding (in-memory fallback).

    Delegates to search_product_vectors for batched numpy computation
    instead of building arrays pair-by-pair in a Python loop.
    """
    if not embeddings:
        return []
    vectors = {item_id: emb for item_id, emb in embeddings}
    return search_product_vectors(query_embedding, vectors, top_k, threshold)
```

Note: `search_product_vectors` is defined *below* `find_similar` in the file — that's fine at call time, but if you prefer, move `find_similar` below it.

- [ ] **Step 4: Update `embed_with_local`**

Replace the `model.encode` call in `embed_with_local`:

```python
    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        batch_size=32,
        normalize_embeddings=True,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_embeddings.py -v`
Expected: all PASS

- [ ] **Step 6: Run full suite and commit**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all pass

```bash
git add backend/grimoire/services/embeddings.py backend/tests/test_embeddings.py
git commit -m "perf(embeddings): batch find_similar via numpy, normalize local embeddings"
```

---

## Task 5: Add pymupdf4llm as the preferred markdown extractor

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/grimoire/processors/text_extractor.py` (new import guard, new function, chain wiring in `extract_text_to_markdown:605-690`, `get_available_extractors:693-701`)
- Test: `backend/tests/test_pymupdf4llm_extraction.py` (create)

**Problem:** `extract_with_pymupdf` dumps raw text blocks with fake `## Page N` headers; the pdfplumber path is ~300 lines of hand-rolled column/heading/footer heuristics. `pymupdf4llm` (PyMuPDF's own LLM-oriented converter, released 2024) produces real headings from font sizes, handles multi-column layouts, tables, and lists — faster and higher quality, which improves FTS and embeddings downstream. Existing extractors stay as fallbacks.

- [ ] **Step 1: Add dependency**

In `backend/requirements.txt`, under `# PDF Processing`, add:

```
pymupdf4llm>=0.0.17
```

Run: `cd backend && pip install pymupdf4llm`
Expected: installs cleanly (pure-Python, depends only on pymupdf).

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_pymupdf4llm_extraction.py`:

```python
"""Tests for the pymupdf4llm extraction backend."""

import pytest

from grimoire.processors.text_extractor import (
    PYMUPDF4LLM_AVAILABLE,
    extract_text_to_markdown,
    extract_with_pymupdf4llm,
    get_available_extractors,
)

pytestmark = pytest.mark.skipif(
    not PYMUPDF4LLM_AVAILABLE, reason="pymupdf4llm not installed"
)


def test_pymupdf4llm_extracts_content(text_pdf):
    md = extract_with_pymupdf4llm(text_pdf)
    assert "Grimoire Test Document" in md


def test_pymupdf4llm_respects_page_range(text_pdf):
    md = extract_with_pymupdf4llm(text_pdf, start_page=1, end_page=1)
    assert "Grimoire Test Document" in md


def test_extract_text_to_markdown_prefers_pymupdf4llm(text_pdf):
    result = extract_text_to_markdown(text_pdf)
    assert result["method"] == "pymupdf4llm"
    assert "Grimoire Test Document" in result["markdown"]
    assert result["total_pages"] == 1


def test_empty_output_falls_through_to_next_backend(text_pdf, monkeypatch):
    from grimoire.processors import text_extractor

    monkeypatch.setattr(
        text_extractor, "extract_with_pymupdf4llm", lambda *a, **k: "   \n  "
    )
    result = text_extractor.extract_text_to_markdown(text_pdf)
    assert result["method"] != "pymupdf4llm"
    assert "Grimoire Test Document" in result["markdown"]


def test_available_extractors_reports_pymupdf4llm():
    assert "pymupdf4llm" in get_available_extractors()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_pymupdf4llm_extraction.py -v`
Expected: FAIL — `ImportError: cannot import name 'PYMUPDF4LLM_AVAILABLE'`

- [ ] **Step 4: Add import guard and extraction function**

In `backend/grimoire/processors/text_extractor.py`, next to the other import guards (after the `markitdown` try/except around line 169):

```python
try:
    import pymupdf4llm
    PYMUPDF4LLM_AVAILABLE = True
except ImportError:
    PYMUPDF4LLM_AVAILABLE = False
```

Add the extraction function near `extract_with_pymupdf`:

```python
def extract_with_pymupdf4llm(
    pdf_path: str | Path,
    start_page: int = 1,
    end_page: int | None = None,
) -> str:
    """Extract markdown using pymupdf4llm.

    Produces real headings (from font sizes), multi-column handling,
    tables, and lists — replaces the hand-rolled heuristics of the
    pymupdf/pdfplumber paths for most documents.
    """
    if not PYMUPDF4LLM_AVAILABLE:
        raise ImportError("pymupdf4llm not available")

    total_pages = _get_page_count(pdf_path)
    if end_page is None:
        end_page = total_pages

    pages = list(range(start_page - 1, min(end_page, total_pages)))
    return pymupdf4llm.to_markdown(str(pdf_path), pages=pages, show_progress=False)
```

- [ ] **Step 5: Wire into the extraction chain**

In `extract_text_to_markdown`, after the marker attempt and **before** the `use_pymupdf` block, insert:

```python
    if markdown_text is None and PYMUPDF4LLM_AVAILABLE:
        try:
            candidate = extract_with_pymupdf4llm(pdf_path, start_page, end_page)
            if candidate and candidate.strip():
                markdown_text = candidate
                method_used = "pymupdf4llm"
        except Exception as e:
            print(f"pymupdf4llm extraction failed: {e}")
```

And in `get_available_extractors`, add to the dict:

```python
        "pymupdf4llm": PYMUPDF4LLM_AVAILABLE,
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_pymupdf4llm_extraction.py -v`
Expected: 5 PASSED

- [ ] **Step 7: Run full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all pass. If any existing test asserts `method == "pymupdf"` on the default chain, update it to `"pymupdf4llm"` — that is the intended new behavior.

- [ ] **Step 8: Sanity-check against a real PDF (manual verification)**

Run from `backend/` with the venv active:

```bash
python -c "
from grimoire.processors.text_extractor import extract_text_to_markdown
import sys, glob
pdfs = glob.glob('../pdfs/*.pdf')
if not pdfs:
    print('no sample pdfs, skipping'); sys.exit(0)
r = extract_text_to_markdown(pdfs[0], end_page=5)
print('method:', r['method'], '| chars:', r['char_count'])
print(r['markdown'][:800])
"
```

Expected: `method: pymupdf4llm`, readable markdown with real `#`-style headings. Eyeball the output for obvious garbage before committing.

- [ ] **Step 9: Commit**

```bash
git add backend/requirements.txt backend/grimoire/processors/text_extractor.py backend/tests/test_pymupdf4llm_extraction.py
git commit -m "feat(extraction): prefer pymupdf4llm for markdown extraction"
```

---

## Task 6: PyMuPDF integrated OCR (poppler path becomes fallback)

**Files:**
- Modify: `backend/grimoire/processors/text_extractor.py` (new `_find_tessdata`, new `extract_with_pymupdf_ocr`, rewire `extract_with_ocr:834-892`)
- Test: `backend/tests/test_ocr_extraction.py` (create)

**Problem:** The OCR path converts pages via a poppler subprocess (`pdf2image`) with temp files, then shells out to Tesseract per page. MuPDF has Tesseract's engine compiled in — `page.get_textpage_ocr()` needs only the **tessdata language files**, no `tesseract.exe`, no poppler, no temp dirs. The old path stays as a fallback (`extract_with_ocr` keeps its signature, so `extract_text_with_ocr_fallback` from Task 2 is untouched).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ocr_extraction.py`:

```python
"""Tests for OCR extraction paths."""

import pytest

from grimoire.processors import text_extractor
from grimoire.processors.text_extractor import _find_tessdata


def test_find_tessdata_env_override(monkeypatch, tmp_path):
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "eng.traineddata").touch()
    monkeypatch.setenv("TESSDATA_PREFIX", str(tessdata))
    assert _find_tessdata() == str(tessdata)


def test_find_tessdata_rejects_dir_without_traineddata(monkeypatch, tmp_path):
    empty = tmp_path / "tessdata"
    empty.mkdir()
    monkeypatch.setenv("TESSDATA_PREFIX", str(empty))
    # Must not accept a dir that has no *.traineddata files
    result = _find_tessdata()
    assert result != str(empty)


@pytest.mark.skipif(
    _find_tessdata() is None, reason="tessdata language files not installed"
)
def test_pymupdf_ocr_reads_scanned_pdf(scanned_pdf):
    text = text_extractor.extract_with_pymupdf_ocr(scanned_pdf)
    assert "GRIMOIRE" in text.upper()


def test_extract_with_ocr_falls_back_when_pymupdf_ocr_fails(scanned_pdf, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no tessdata")

    monkeypatch.setattr(text_extractor, "extract_with_pymupdf_ocr", boom)
    monkeypatch.setattr(
        text_extractor, "_extract_with_pdf2image_ocr",
        lambda *a, **k: "## Page 1\n\nLEGACY OCR\n\n",
    )
    result = text_extractor.extract_with_ocr(scanned_pdf)
    assert "LEGACY OCR" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ocr_extraction.py -v`
Expected: FAIL — `ImportError: cannot import name '_find_tessdata'`

- [ ] **Step 3: Implement `_find_tessdata`**

In `backend/grimoire/processors/text_extractor.py`, add after `_find_tesseract`:

```python
def _find_tessdata() -> str | None:
    """Locate the Tesseract language-data directory (tessdata).

    PyMuPDF's built-in OCR needs only these files — not tesseract.exe.
    A directory counts only if it contains at least one *.traineddata.
    """
    import os

    def _valid(p: Path) -> bool:
        return p.is_dir() and any(p.glob("*.traineddata"))

    env = os.environ.get("TESSDATA_PREFIX")
    if env and _valid(Path(env)):
        return env

    # Derive from a tesseract install if present
    tesseract = _find_tesseract()
    if tesseract:
        candidate = Path(tesseract).parent / "tessdata"
        if _valid(candidate):
            return str(candidate)

    # Common Linux/Docker locations (tesseract-ocr package)
    for p in (
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tesseract-ocr/4.00/tessdata",
        "/usr/share/tessdata",
    ):
        if _valid(Path(p)):
            return p

    return None
```

- [ ] **Step 4: Implement `extract_with_pymupdf_ocr` and rewire `extract_with_ocr`**

Rename the existing `extract_with_ocr` (lines 834-892) to `_extract_with_pdf2image_ocr` — body unchanged. Then add:

```python
def extract_with_pymupdf_ocr(
    pdf_path: str | Path,
    start_page: int = 1,
    end_page: int | None = None,
    dpi: int = 200,
    lang: str = "eng",
) -> str:
    """OCR using MuPDF's integrated Tesseract engine.

    No poppler, no subprocess-per-page, no temp files — MuPDF renders
    and OCRs in-process using the tessdata language files.
    """
    if not PYMUPDF_AVAILABLE:
        raise ImportError("PyMuPDF not available")

    import os

    tessdata = _find_tessdata()
    if tessdata is None:
        raise RuntimeError("tessdata language files not found")
    os.environ.setdefault("TESSDATA_PREFIX", tessdata)

    markdown_content = []
    doc = fitz.open(str(pdf_path))
    try:
        total_pages = len(doc)
        if end_page is None:
            end_page = total_pages

        for page_num in range(start_page - 1, min(end_page, total_pages)):
            page = doc[page_num]
            tp = page.get_textpage_ocr(
                flags=0, language=lang, dpi=dpi, full=True, tessdata=tessdata
            )
            text = clean_text(page.get_text(textpage=tp))

            markdown_content.append(f"## Page {page_num + 1}\n\n")
            if text.strip():
                markdown_content.append(text + "\n\n")
            markdown_content.append("\n---\n\n")
    finally:
        doc.close()

    return "".join(markdown_content)


def extract_with_ocr(
    pdf_path: str | Path,
    start_page: int = 1,
    end_page: int | None = None,
    dpi: int = 200,
    lang: str = "eng",
) -> str:
    """OCR a PDF: try MuPDF's integrated Tesseract, fall back to
    pdf2image + pytesseract if tessdata is missing or OCR fails."""
    try:
        return extract_with_pymupdf_ocr(pdf_path, start_page, end_page, dpi, lang)
    except Exception as e:
        print(f"PyMuPDF OCR failed ({e}), falling back to pdf2image path")

    if not TESSERACT_AVAILABLE:
        raise ImportError(
            "OCR unavailable: PyMuPDF OCR failed and pytesseract/pdf2image not installed"
        )
    return _extract_with_pdf2image_ocr(pdf_path, start_page, end_page, dpi, lang)
```

Note on the `tessdata=` keyword: supported in `get_textpage_ocr` on recent PyMuPDF. If the installed version rejects it (`TypeError: unexpected keyword argument`), drop the keyword — the `TESSDATA_PREFIX` env var set above is sufficient. Check with `python -c "import fitz; print(fitz.__doc__)"` for the version.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ocr_extraction.py -v`
Expected: PASS (the `test_pymupdf_ocr_reads_scanned_pdf` test may SKIP on machines without tessdata — that is acceptable)

- [ ] **Step 6: Run full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/processors/text_extractor.py backend/tests/test_ocr_extraction.py
git commit -m "perf(ocr): use MuPDF integrated Tesseract, demote poppler path to fallback"
```

---

## Task 7: Gallery image dedup + faster hashing + render cap

**Files:**
- Modify: `backend/grimoire/processors/image_extractor.py:92-154` (`extract_images_from_page`), `:258-312` (`extract_images`), `:315-348` (`_extract_image_by_xref`), `:351-377` (`_render_page`)
- Test: `backend/tests/test_image_extraction.py` (create)

**Problems:** (a) the gallery-path `extract_images()` saves the same repeated art (page borders, logos) once per occurrence — disk waste plus WebP re-encoding time, which dominates; (b) MD5 for dedup hashing — `blake2b` is faster stdlib; (c) `_render_page` renders at fixed 2×2 with no cap, so a large-format map page can produce an enormous pixmap.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_image_extraction.py`:

```python
"""Tests for gallery image extraction."""

import fitz
import pytest

from grimoire.processors.image_extractor import _render_scale, extract_images


def test_extract_images_dedupes_repeated_image(repeated_image_pdf, tmp_path):
    out_dir = tmp_path / "gallery"
    manifest = extract_images(repeated_image_pdf, out_dir)
    # Same image on 3 pages must be saved exactly once
    assert manifest["image_count"] == 1
    assert manifest["total_pages"] == 3
    saved = [p for p in out_dir.iterdir() if p.name != "manifest.json"]
    assert len(saved) == 1


def test_render_scale_normal_page_keeps_2x():
    # Letter page at 2x is 1224x1584 — under the cap, unchanged
    assert _render_scale(612, 792) == 2.0


def test_render_scale_caps_huge_pages():
    # A 3000pt-wide map page must be capped to ~2048px output
    scale = _render_scale(3000, 2000)
    assert scale == pytest.approx(2048 / 3000)
    assert scale < 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_image_extraction.py -v`
Expected: FAIL — `ImportError: cannot import name '_render_scale'`

- [ ] **Step 3: Implement dedup, blake2b, and render cap**

In `backend/grimoire/processors/image_extractor.py`:

**(a)** In `extract_images_from_page` (line 123), replace the MD5 hash:

```python
            img_hash = hashlib.blake2b(image_data, digest_size=8).hexdigest()
```

**(b)** Change `_extract_image_by_xref` to accept and enforce a seen-hash set:

```python
def _extract_image_by_xref(
    doc, xref: int, output_dir: Path, index: int,
    seen_hashes: set[str] | None = None,
) -> dict | None:
    """Extract a single image by its xref and save as WebP.

    Returns None for images whose bytes were already saved (dedup).
    """
    base_image = doc.extract_image(xref)
    if not base_image or not base_image.get("image"):
        return None

    image_bytes = base_image["image"]

    if seen_hashes is not None:
        img_hash = hashlib.blake2b(image_bytes, digest_size=8).hexdigest()
        if img_hash in seen_hashes:
            return None
        seen_hashes.add(img_hash)

    width = base_image.get("width", 0)
    height = base_image.get("height", 0)
    original_ext = base_image.get("ext", "png")
    # ... rest of the function body unchanged from here ...
```

**(c)** In `extract_images`, thread the set through. Replace the loop section:

```python
    images = []
    image_index = 0
    seen_xrefs: set[int] = set()
    seen_hashes: set[str] = set()

    for page_num, page in enumerate(doc):
        page_images = page.get_images(full=True)

        if page_images:
            for img_info in page_images:
                xref = img_info[0]
                if xref in seen_xrefs:
                    continue  # same object reused on another page
                seen_xrefs.add(xref)
                try:
                    extracted = _extract_image_by_xref(
                        doc, xref, output_dir, image_index, seen_hashes
                    )
                    if extracted:
                        extracted["page"] = page_num + 1
                        images.append(extracted)
                        image_index += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to extract image xref {xref} from page {page_num + 1}: {e}"
                    )
        else:
            extracted = _render_page(page, output_dir, image_index, page_num)
            if extracted:
                images.append(extracted)
                image_index += 1
```

**(d)** Add `_render_scale` above `_render_page` and use it:

```python
def _render_scale(page_width: float, page_height: float, max_px: int = 2048) -> float:
    """2x render scale, capped so no output dimension exceeds max_px.

    Prevents enormous pixmaps for large-format pages (poster maps)."""
    max_dim = max(page_width, page_height)
    if max_dim <= 0:
        return 1.0
    return min(2.0, max_px / max_dim)
```

In `_render_page`, replace `mat = fitz.Matrix(2, 2)` with:

```python
        scale = _render_scale(page.rect.width, page.rect.height)
        mat = fitz.Matrix(scale, scale)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_image_extraction.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Run full suite (gallery tests must stay green)**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all pass. The gallery feature has existing tests — if any assert exact image counts on multi-page fixtures with repeated art, the new (correct) deduped counts apply; update assertions accordingly and note it in the commit message.

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/processors/image_extractor.py backend/tests/test_image_extraction.py
git commit -m "perf(gallery): dedupe repeated images, blake2b hashing, cap page-render size"
```

---

## Task 8: Infrastructure cleanup — Python 3.12 Docker image, asyncio.run

**Files:**
- Modify: `docker/Dockerfile.backend:2`
- Modify: `backend/grimoire/worker/tasks.py:12-19` (`run_async`)

- [ ] **Step 1: Bump Docker base image**

In `docker/Dockerfile.backend`, change line 2:

```dockerfile
FROM python:3.12-slim
```

(Local dev already runs 3.12; 3.12 is ~5-10% faster than 3.11 across the board.)

- [ ] **Step 2: Simplify `run_async`**

In `backend/grimoire/worker/tasks.py`, replace the function:

```python
def run_async(coro):
    """Run an async function in a sync context (Huey worker threads)."""
    return asyncio.run(coro)
```

`asyncio.run` creates and closes a fresh loop exactly like the hand-rolled version, with proper async-generator shutdown that the old version skipped.

- [ ] **Step 3: Run full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all pass

- [ ] **Step 4: Verify Docker build (optional — requires Docker running)**

Run from repo root: `docker compose -f docker/docker-compose.yml --project-directory . build grimoire`
Expected: builds successfully. If Docker is unavailable in the execution environment, skip and flag for the user to verify.

- [ ] **Step 5: Commit**

```bash
git add docker/Dockerfile.backend backend/grimoire/worker/tasks.py
git commit -m "chore: bump Docker to Python 3.12, use asyncio.run in worker"
```

---

## Final verification

- [ ] Run the entire suite one last time: `cd backend && python -m pytest tests/ -v` — all green.
- [ ] Confirm no stray debug output was added (`git diff main --stat` shows only intended files).
- [ ] Manual smoke test if a real library is available: trigger a rescan of a small folder from the UI and confirm covers, text extraction, and the gallery all still work; note that new scans should be visibly faster.

## Execution notes for the agent

- Tasks 1–4 and 7–8 are independent of each other. Task 2 must precede Task 5 (Task 5 uses `_get_page_count`) and Task 6 (Task 6's fallback tests rely on Task 2's reordered flow). Execute in numbered order unless parallelizing deliberately.
- If `pymupdf4llm.to_markdown` behaves differently than shown (API drift), check `pip show pymupdf4llm` and the signature via `python -c "import pymupdf4llm, inspect; print(inspect.signature(pymupdf4llm.to_markdown))"` — adjust the call, not the test expectations.
- Never weaken a test to make it pass. If a test exposes a real behavior conflict with existing code, stop and surface it.
