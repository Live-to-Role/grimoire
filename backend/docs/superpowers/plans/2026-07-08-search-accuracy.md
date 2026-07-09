# Search Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Library semantic search return relevant results for natural queries ("Undead adventure for 3rd level characters") via page-anchored chunks, query interpretation, and two-stage chunk-level retrieval.

**Architecture:** Phase 0 changes what extraction/embedding writes (per-page markdown in the extracted-text JSON, page-tagged 1000-char chunks in `ProductEmbedding`) and MUST merge before the mass re-extract/re-embed pass. Phase 1 adds `services/query_interpreter.py` (regex heuristics always, optional Claude/OpenAI refinement). Phase 2 adds `services/search_service.py`: candidate union (cached averaged-vector search ∪ BM25, pre-filtered) → chunk re-rank (top-3-mean cosine) → RRF fusion → threshold on chunk scores; `/semantic/search` becomes a thin wrapper. Plus DCC level backfill and a golden-query eval script.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, SQLite/aiosqlite, numpy, httpx, pymupdf4llm; React 18 + TypeScript frontend.

**Spec:** `backend/docs/superpowers/specs/2026-07-08-search-accuracy-design.md`

## Global Constraints

- **Branch:** create `feat/search-accuracy` off `main` AFTER `feat/oversized-guard` merges. Never switch branches while another session is active on this checkout. **The full-library re-extract/re-embed must not start until Tasks 1–4 (Phase 0) merge.**
- Backend tests run from `backend/` with `C:/Users/mkemi/miniconda3/python.exe -m pytest`. Baseline at branch time: all currently-passing tests keep passing; 6 pre-existing failures are known — do NOT fix them.
- Frontend gate: `npx tsc -b` from `frontend/`. One pre-existing error in `Settings.tsx` ('Shield') is baseline.
- Chunking constants: **chunk_size 1000, overlap 100** — exact values, everywhere (replacing 500/50).
- Retrieval constants (module-level in `search_service.py`, tunable via Task 11): `CANDIDATES_PER_SOURCE = 150`, `MAX_CANDIDATES = 200`, `TOP_K_CHUNKS = 3`, `CHUNK_SCORE_THRESHOLD = 0.45`, `SEMANTIC_RRF_WEIGHT = 1.0`, `KEYWORD_RRF_WEIGHT = 1.0`.
- LLM interpreter: Anthropic model `claude-haiku-4-5` (exact string), OpenAI fallback `gpt-4o-mini`, raw httpx (matches the codebase's existing provider-call pattern), 5s timeout, never blocks search on failure.
- Never run `python -m grimoire.worker.run` (it hangs).
- Grimoire is local-only, single-user. No deployment concerns.

---

### Task 1: Page-aware extraction (`text_extractor.py`)

**Files:**
- Modify: `backend/grimoire/processors/text_extractor.py` (pymupdf4llm branch of `extract_text_to_markdown` at lines 737–744; add two functions near `extract_with_pymupdf4llm` at line 481)
- Test: `backend/tests/processors/test_page_extraction.py` (create; create `backend/tests/processors/__init__.py` if missing)

**Interfaces:**
- Consumes: existing `extract_with_pymupdf4llm`, `_get_page_count`, `PYMUPDF4LLM_AVAILABLE`.
- Produces:
  - `extract_with_pymupdf4llm_pages(pdf_path, start_page=1, end_page=None) -> list[dict]` — entries `{"page": <1-based int>, "markdown": str}`.
  - `split_pages_by_markers(markdown: str) -> list[dict] | None` — splits on the `## Page N` headings that the pymupdf/pdfplumber/OCR paths already emit; `None` when no markers.
  - `extract_text_to_markdown(...)` result dict gains a `"pages"` key (same entry shape) whenever page info is available; `"markdown"` stays as-is (joined full text) so every existing reader keeps working.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/processors/test_page_extraction.py`:

```python
"""Page-anchored extraction: per-page markdown from pymupdf4llm + marker splitting."""
from pathlib import Path

import pytest

from grimoire.processors.text_extractor import (
    PYMUPDF4LLM_AVAILABLE,
    extract_text_to_markdown,
    extract_with_pymupdf4llm_pages,
    split_pages_by_markers,
)


@pytest.fixture
def three_page_pdf(tmp_path) -> Path:
    """Create a 3-page PDF with distinct text per page."""
    import fitz

    path = tmp_path / "three.pdf"
    doc = fitz.open()
    for i, word in enumerate(["alpha", "bravo", "charlie"], start=1):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i} content: {word} " * 5)
    doc.save(str(path))
    doc.close()
    return path


@pytest.mark.skipif(not PYMUPDF4LLM_AVAILABLE, reason="pymupdf4llm not installed")
def test_pymupdf4llm_pages_returns_one_entry_per_page(three_page_pdf):
    pages = extract_with_pymupdf4llm_pages(three_page_pdf)
    assert [p["page"] for p in pages] == [1, 2, 3]
    assert "alpha" in pages[0]["markdown"]
    assert "charlie" in pages[2]["markdown"]


@pytest.mark.skipif(not PYMUPDF4LLM_AVAILABLE, reason="pymupdf4llm not installed")
def test_pymupdf4llm_pages_respects_page_range(three_page_pdf):
    pages = extract_with_pymupdf4llm_pages(three_page_pdf, start_page=2, end_page=3)
    assert [p["page"] for p in pages] == [2, 3]
    assert "bravo" in pages[0]["markdown"]


def test_split_pages_by_markers_basic():
    md = "## Page 1\n\nfirst page text\n\n---\n\n## Page 2\n\nsecond page text\n"
    pages = split_pages_by_markers(md)
    assert [p["page"] for p in pages] == [1, 2]
    assert "first page text" in pages[0]["markdown"]
    assert "second page text" in pages[1]["markdown"]
    # Joining the segments reproduces the original text exactly
    assert "".join(p["markdown"] for p in pages) == md


def test_split_pages_by_markers_preamble_attaches_to_first_page():
    md = "Some front matter\n\n## Page 1\n\nbody\n\n## Page 2\n\nmore\n"
    pages = split_pages_by_markers(md)
    assert pages[0]["page"] == 1
    assert "Some front matter" in pages[0]["markdown"]


def test_split_pages_by_markers_returns_none_without_markers():
    assert split_pages_by_markers("just a flat blob of text") is None


@pytest.mark.skipif(not PYMUPDF4LLM_AVAILABLE, reason="pymupdf4llm not installed")
def test_extract_text_to_markdown_includes_pages(three_page_pdf):
    result = extract_text_to_markdown(three_page_pdf)
    assert "error" not in result
    assert result["method"] == "pymupdf4llm"
    assert [p["page"] for p in result["pages"]] == [1, 2, 3]
    # markdown key still present and is the joined page text
    assert result["markdown"] == "\n\n".join(p["markdown"] for p in result["pages"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/processors/test_page_extraction.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_with_pymupdf4llm_pages'`.

- [ ] **Step 3: Add the two functions**

In `backend/grimoire/processors/text_extractor.py`, directly below `extract_with_pymupdf4llm` (after line 500):

```python
def extract_with_pymupdf4llm_pages(
    pdf_path: str | Path,
    start_page: int = 1,
    end_page: int | None = None,
) -> list[dict]:
    """Extract per-page markdown using pymupdf4llm's page_chunks mode.

    Returns a list of {"page": <1-based page number>, "markdown": str}.
    Page numbers come from the indices we request, not from pymupdf4llm
    metadata, so they are correct regardless of library version.
    """
    if not PYMUPDF4LLM_AVAILABLE:
        raise ImportError("pymupdf4llm not available")

    total_pages = _get_page_count(pdf_path)
    if end_page is None:
        end_page = total_pages

    page_indices = list(range(start_page - 1, min(end_page, total_pages)))
    chunks = pymupdf4llm.to_markdown(
        str(pdf_path), pages=page_indices, page_chunks=True, show_progress=False
    )
    return [
        {"page": idx + 1, "markdown": chunk["text"]}
        for idx, chunk in zip(page_indices, chunks)
    ]


_PAGE_MARKER_RE = re.compile(r"^## Page (\d+)\s*$", re.MULTILINE)


def split_pages_by_markers(markdown: str) -> list[dict] | None:
    """Split markdown into per-page segments on the '## Page N' headings the
    pymupdf/pdfplumber/OCR extractors emit. Returns None when no markers exist
    (marker/markitdown output). Segments concatenate back to the input exactly;
    any front matter before the first marker attaches to the first page.
    """
    matches = list(_PAGE_MARKER_RE.finditer(markdown))
    if not matches:
        return None
    pages = []
    for i, m in enumerate(matches):
        start = 0 if i == 0 else m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        pages.append({"page": int(m.group(1)), "markdown": markdown[start:end]})
    return pages
```

(`re` is already imported at the top of the file.)

- [ ] **Step 4: Wire pages into `extract_text_to_markdown`**

Replace the pymupdf4llm branch (currently lines 737–744):

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

with:

```python
    pages_list: list[dict] | None = None

    if markdown_text is None and PYMUPDF4LLM_AVAILABLE:
        try:
            page_entries = extract_with_pymupdf4llm_pages(pdf_path, start_page, end_page)
            candidate = "\n\n".join(p["markdown"] for p in page_entries)
            if candidate and candidate.strip():
                markdown_text = candidate
                pages_list = page_entries
                method_used = "pymupdf4llm"
        except Exception as e:
            print(f"pymupdf4llm extraction failed: {e}")
```

Then replace the final `return { ... }` block (currently lines 775–781):

```python
    result = {
        "markdown": markdown_text,
        "total_pages": total_pages,
        "pages_extracted": f"{start_page}-{end_page}",
        "method": method_used,
        "char_count": len(markdown_text),
    }
    # pymupdf/pdfplumber emit "## Page N" headings — recover pages from those
    # when the page_chunks path didn't run.
    if pages_list is None:
        pages_list = split_pages_by_markers(markdown_text)
    if pages_list:
        result["pages"] = pages_list
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/processors/test_page_extraction.py -v`
Expected: PASS (7 passed, or with skips if pymupdf4llm missing — it is installed in this env, so expect 0 skips).

- [ ] **Step 6: Run existing extraction tests for regressions**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/ -k "extract" -v`
Expected: no new failures vs baseline.

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/processors/text_extractor.py backend/tests/processors/test_page_extraction.py backend/tests/processors/__init__.py
git commit -m "feat(extract): page-anchored extraction via page_chunks + page-marker splitting"
```

---

### Task 2: Persist pages + `get_extracted_pages` accessor

**Files:**
- Modify: `backend/grimoire/services/processor.py` (add accessor near `get_extracted_text` at line 240)
- Modify: `backend/grimoire/services/queue_processor.py` (`_save_ocr_result` inside `handle_ocr_text_task`, lines 392–414)
- Test: `backend/tests/services/test_extracted_pages.py` (create)

**Interfaces:**
- Consumes: `split_pages_by_markers` from Task 1; `extract_text_to_markdown` already returns `"pages"` and `process_text_extraction_sync` dumps the whole result dict to JSON, so text-extraction persistence is automatic — only the OCR handler builds its own JSON and needs the key added.
- Produces: `get_extracted_pages(product) -> list[dict] | None` in `grimoire/services/processor.py` — reads the extracted-text JSON, returns the `"pages"` list or `None` (legacy files). `get_extracted_text` is unchanged (the `"markdown"` key is still always written).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_extracted_pages.py`:

```python
"""get_extracted_pages accessor + OCR handler page persistence."""
import json

from grimoire.services.processor import get_extracted_pages, get_extracted_text


class FakeProduct:
    def __init__(self, path):
        self.text_extracted = True
        self.extracted_text_path = str(path)


def _write(tmp_path, data):
    f = tmp_path / "1.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


def test_pages_returned_when_present(tmp_path):
    f = _write(tmp_path, {
        "markdown": "## Page 1\n\nhello\n",
        "pages": [{"page": 1, "markdown": "## Page 1\n\nhello\n"}],
    })
    pages = get_extracted_pages(FakeProduct(f))
    assert pages == [{"page": 1, "markdown": "## Page 1\n\nhello\n"}]


def test_pages_none_for_legacy_flat_file(tmp_path):
    f = _write(tmp_path, {"markdown": "flat text only"})
    assert get_extracted_pages(FakeProduct(f)) is None
    # legacy reads still work
    assert get_extracted_text(FakeProduct(f)) == "flat text only"


def test_pages_none_when_file_missing(tmp_path):
    p = FakeProduct(tmp_path / "nope.json")
    assert get_extracted_pages(p) is None


def test_pages_none_when_not_extracted(tmp_path):
    p = FakeProduct(tmp_path / "1.json")
    p.text_extracted = False
    assert get_extracted_pages(p) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_extracted_pages.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_extracted_pages'`.

- [ ] **Step 3: Add the accessor**

In `backend/grimoire/services/processor.py`, directly below `get_extracted_text` (after line 263):

```python
def get_extracted_pages(product: Product) -> list[dict] | None:
    """Get per-page extracted markdown for a product.

    Returns the "pages" list ([{"page": int, "markdown": str}, ...]) when the
    extraction JSON carries page anchors, or None for legacy flat files.
    """
    import json

    if not product.text_extracted or not product.extracted_text_path:
        return None

    text_path = Path(product.extracted_text_path)
    if not text_path.exists():
        return None

    try:
        with open(text_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("pages")
    except Exception:
        return None
```

- [ ] **Step 4: Add pages to the OCR handler's JSON**

In `backend/grimoire/services/queue_processor.py`, inside `_save_ocr_result` (line 402), change the `result` dict from:

```python
            result = {
                "markdown": markdown_text,
                "total_pages": total_pages,
                "pages_extracted": f"1-{total_pages}",
                "method": "tesseract_ocr",
                "char_count": len(markdown_text),
                "ocr_used": True,
            }
```

to:

```python
            from grimoire.processors.text_extractor import split_pages_by_markers

            result = {
                "markdown": markdown_text,
                "total_pages": total_pages,
                "pages_extracted": f"1-{total_pages}",
                "method": "tesseract_ocr",
                "char_count": len(markdown_text),
                "ocr_used": True,
            }
            pages = split_pages_by_markers(markdown_text)
            if pages:
                result["pages"] = pages
```

(The OCR extractors emit `## Page N` headings — `extract_with_pymupdf_ocr` line 1023 — so the splitter recovers real pages.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_extracted_pages.py tests/services/ -v`
Expected: new tests PASS; no new failures elsewhere.

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/services/processor.py backend/grimoire/services/queue_processor.py backend/tests/services/test_extracted_pages.py
git commit -m "feat(extract): persist page anchors in OCR JSON + get_extracted_pages accessor"
```

---

### Task 3: Page-aware chunker + chunk-size 1000/100 + `ProductEmbedding` page columns

**Files:**
- Modify: `backend/grimoire/services/embeddings.py` (`chunk_text` at line 290; add `_chunks_with_spans`, `chunk_text_with_pages`, `build_chunks_for_product`)
- Modify: `backend/grimoire/models/embedding.py` (add `page_start`, `page_end` columns)
- Modify: `backend/grimoire/database.py` (`_ensure_columns` migrations list at line 146)
- Modify: `backend/grimoire/api/routes/semantic.py` (`EmbedProductRequest.chunk_size` default at line 65; `embed-batch` `chunk_size` Query default at line 395)
- Test: `backend/tests/test_chunking.py` (create)

**Interfaces:**
- Consumes: existing `chunk_text` boundary heuristics (sentence-end search in the last 100 chars).
- Produces:
  - `_chunks_with_spans(text, chunk_size=1000, overlap=100) -> list[tuple[str, tuple[int, int]]]` — chunk text plus its (start, end) char span in the input; `chunk_text` delegates to it (identical output to today except new size defaults).
  - `chunk_text_with_pages(pages, chunk_size=1000, overlap=100) -> list[tuple[str, int, int]]` — `(chunk_text, page_start, page_end)`; pages is the Task 1/2 entry list.
  - `build_chunks_for_product(preamble, pages, flat_text, chunk_size=1000, overlap=100) -> list[tuple[str, int | None, int | None]]` — preamble chunk(s) first with `(None, None)` pages, then page-mapped content chunks (or flat `(None, None)` chunks when `pages` is None).
  - `ProductEmbedding.page_start` / `.page_end` — nullable Integer columns (DDL via `_ensure_columns` for existing DBs).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_chunking.py`:

```python
"""Page-aware chunking: span mapping, page attribution, preamble handling."""
from grimoire.services.embeddings import (
    build_chunks_for_product,
    chunk_text,
    chunk_text_with_pages,
)


def _pages(sizes):
    """Build synthetic pages with known sizes; page text is 'pN ' repeated."""
    return [
        {"page": i + 1, "markdown": (f"p{i + 1} " * (size // 3)).strip()}
        for i, size in enumerate(sizes)
    ]


def test_chunk_text_default_is_1000():
    text = "word " * 1000  # 5000 chars
    chunks = chunk_text(text)
    assert all(len(c) <= 1100 for c in chunks)  # 1000 + boundary slack
    assert len(chunks) < 8  # ~5000/900 with overlap; 500-char chunks would give 11+


def test_single_page_chunks_carry_that_page():
    chunks = chunk_text_with_pages(_pages([2500]))
    assert len(chunks) >= 2
    assert all(ps == 1 and pe == 1 for _, ps, pe in chunks)


def test_cross_page_chunk_gets_a_range():
    # Two small pages: the chunk spanning both must report pages 1-2
    chunks = chunk_text_with_pages(_pages([600, 600]))
    spans = [(ps, pe) for _, ps, pe in chunks]
    assert (1, 2) in spans or ((1, 1) in spans and (2, 2) in spans and len(chunks) > 1)
    # At minimum: first chunk starts on page 1, last chunk ends on page 2
    assert chunks[0][1] == 1
    assert chunks[-1][2] == 2


def test_chunks_concatenate_to_full_content():
    pages = _pages([1500, 1500])
    chunks = chunk_text_with_pages(pages)
    # Every chunk's text appears in the joined page text
    joined = "\n\n".join(p["markdown"] for p in pages)
    for text, _, _ in chunks:
        assert text in joined


def test_build_chunks_preamble_has_null_pages():
    pages = _pages([1500])
    result = build_chunks_for_product("Title: X\nGame System: Y\n\n", pages, "")
    assert result[0][1] is None and result[0][2] is None  # preamble chunk
    assert "Title: X" in result[0][0]
    assert result[1][1] == 1  # first content chunk on page 1


def test_build_chunks_flat_fallback_when_no_pages():
    result = build_chunks_for_product("pre\n\n", None, "flat body " * 300)
    assert all(ps is None and pe is None for _, ps, pe in result)
    assert len(result) >= 2  # preamble + flat content chunks


def test_empty_preamble_skipped():
    result = build_chunks_for_product("", _pages([500]), "")
    assert result[0][1] == 1  # first chunk is content, not preamble
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_chunking.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_chunks_for_product'`.

- [ ] **Step 3: Refactor `chunk_text` into span form and add the new functions**

In `backend/grimoire/services/embeddings.py`, replace `chunk_text` (lines 290–324) with:

```python
def _chunks_with_spans(
    text: str, chunk_size: int = 1000, overlap: int = 100
) -> list[tuple[str, tuple[int, int]]]:
    """Chunk text and report each chunk's (start, end) char span in the input.

    Same boundary heuristics as the original chunk_text: prefer to break at a
    sentence end found within the last 100 chars of the window.
    """
    if len(text) <= chunk_size:
        stripped = text.strip()
        return [(stripped, (0, len(text)))] if stripped else []

    out: list[tuple[str, tuple[int, int]]] = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            search_start = max(end - 100, start)
            for punct in ['. ', '! ', '? ', '\n\n', '\n']:
                pos = text.rfind(punct, search_start, end)
                if pos > start:
                    end = pos + len(punct)
                    break

        chunk = text[start:end].strip()
        if chunk:
            out.append((chunk, (start, min(end, len(text)))))
        start = end - overlap

    return out


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks for embedding."""
    return [chunk for chunk, _ in _chunks_with_spans(text, chunk_size, overlap)]


_PAGE_JOIN = "\n\n"


def chunk_text_with_pages(
    pages: list[dict], chunk_size: int = 1000, overlap: int = 100
) -> list[tuple[str, int, int]]:
    """Chunk per-page markdown into (chunk_text, page_start, page_end) tuples.

    Concatenates page texts with tracked offsets, chunks the joined text with
    the standard algorithm, then maps each chunk's char span back to a
    (page_start, page_end) range. Cross-page chunks get a real range.
    """
    import bisect

    page_starts: list[int] = []
    page_numbers: list[int] = []
    parts: list[str] = []
    pos = 0
    for p in pages:
        page_starts.append(pos)
        page_numbers.append(p["page"])
        parts.append(p["markdown"])
        pos += len(p["markdown"]) + len(_PAGE_JOIN)
    full = _PAGE_JOIN.join(parts)

    def page_at(offset: int) -> int:
        i = bisect.bisect_right(page_starts, offset) - 1
        return page_numbers[max(i, 0)]

    return [
        (chunk, page_at(span[0]), page_at(max(span[1] - 1, span[0])))
        for chunk, span in _chunks_with_spans(full, chunk_size, overlap)
    ]


def build_chunks_for_product(
    preamble: str,
    pages: list[dict] | None,
    flat_text: str,
    chunk_size: int = 1000,
    overlap: int = 100,
) -> list[tuple[str, int | None, int | None]]:
    """Build the full chunk list for a product: metadata preamble chunk(s)
    first (page NULL), then page-mapped content chunks — or flat chunks with
    NULL pages when no page anchors exist (legacy extractions).

    The preamble stays chunk 0 so compute_weighted_average_vector's
    metadata_weight keeps boosting it.
    """
    chunks: list[tuple[str, int | None, int | None]] = []
    if preamble and preamble.strip():
        for c in chunk_text(preamble, chunk_size, overlap):
            chunks.append((c, None, None))
    if pages:
        chunks.extend(chunk_text_with_pages(pages, chunk_size, overlap))
    else:
        for c in chunk_text(flat_text, chunk_size, overlap):
            chunks.append((c, None, None))
    return chunks
```

- [ ] **Step 4: Add the model columns and migration entries**

In `backend/grimoire/models/embedding.py`, after the `embedding_dim` column (line 33):

```python
    # 1-based page range this chunk came from (NULL for metadata preamble
    # chunks and legacy flat extractions)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
```

In `backend/grimoire/database.py`, append to the `migrations` list in `_ensure_columns` (line 146):

```python
        ("product_embeddings", "page_start", "INTEGER"),
        ("product_embeddings", "page_end", "INTEGER"),
```

- [ ] **Step 5: Bump the API-side chunk_size defaults**

In `backend/grimoire/api/routes/semantic.py`:
- Line 65: `chunk_size: int = Field(500, ge=100, le=2000)` → `chunk_size: int = Field(1000, ge=100, le=2000)`
- Line 66: `overlap: int = Field(50, ge=0, le=200)` → `overlap: int = Field(100, ge=0, le=200)`
- Line 395 (`embed_batch`): `chunk_size: int = Query(500, ge=100, le=2000)` → `chunk_size: int = Query(1000, ge=100, le=2000)`

- [ ] **Step 6: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_chunking.py tests/test_embeddings.py -v`
Expected: new tests PASS; `test_embeddings.py` no new failures (if any existing test asserts 500-char chunking behavior, update its explicit sizes — do not weaken assertions).

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/services/embeddings.py backend/grimoire/models/embedding.py backend/grimoire/database.py backend/grimoire/api/routes/semantic.py backend/tests/test_chunking.py
git commit -m "feat(embed): page-aware chunker, 1000/100 chunk defaults, page columns on ProductEmbedding"
```

---

### Task 4: Wire page-aware chunking into all three embed paths

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py` (`handle_embed_task`, lines 447–530: `_read_extracted_text` + chunking + record creation)
- Modify: `backend/grimoire/api/routes/semantic.py` (`embed_product` lines 161–244, `embed_batch` lines 389–472)
- Test: `backend/tests/services/test_embed_pages.py` (create)

**Interfaces:**
- Consumes: `build_chunks_for_product` (Task 3), `get_extracted_pages` (Task 2), existing `build_metadata_preamble`, `generate_embeddings`, `compute_weighted_average_vector`, `invalidate_vector_cache`.
- Produces: all embed paths store `ProductEmbedding` rows with `page_start`/`page_end` populated (NULL for preamble/legacy). No signature changes.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_embed_pages.py`:

```python
"""handle_embed_task stores page anchors on chunk rows."""
import json

import pytest
from sqlalchemy import select

from grimoire.models import Product, ProductEmbedding
from grimoire.services import queue_processor
from grimoire.services.embeddings import EmbeddingResult


@pytest.fixture
def fake_embeddings(monkeypatch):
    async def _fake(texts, provider=None, model=None):
        # deterministic 8-dim unit-ish vectors
        return [
            EmbeddingResult(embedding=[float(i + 1)] * 8, model="fake-model")
            for i, _ in enumerate(texts)
        ]

    monkeypatch.setattr(queue_processor, "generate_embeddings", _fake, raising=False)
    import grimoire.services.embeddings as emb
    monkeypatch.setattr(emb, "generate_embeddings", _fake)
    return _fake


async def test_embed_task_stores_page_anchors(db, tmp_path, fake_embeddings):
    body = ("lorem ipsum " * 120).strip()  # ~1400 chars -> 2+ chunks
    text_file = tmp_path / "p.json"
    text_file.write_text(json.dumps({
        "markdown": f"## Page 1\n\n{body}\n\n## Page 2\n\n{body}\n",
        "pages": [
            {"page": 1, "markdown": f"## Page 1\n\n{body}\n\n"},
            {"page": 2, "markdown": f"## Page 2\n\n{body}\n"},
        ],
    }), encoding="utf-8")

    product = Product(
        file_path="/x/p.pdf", file_name="p.pdf", file_hash="embed-pages-1",
        title="Paged Book", text_extracted=True,
        extracted_text_path=str(text_file),
    )
    db.add(product)
    await db.commit()

    ok = await queue_processor.handle_embed_task(db, product)
    assert ok is True

    rows = (await db.execute(
        select(ProductEmbedding)
        .where(ProductEmbedding.product_id == product.id)
        .order_by(ProductEmbedding.chunk_index)
    )).scalars().all()
    assert len(rows) >= 3
    # chunk 0 is the metadata preamble -> NULL pages
    assert rows[0].page_start is None and rows[0].page_end is None
    # content chunks carry real page numbers
    content = rows[1:]
    assert all(r.page_start is not None for r in content)
    assert content[0].page_start == 1
    assert content[-1].page_end == 2


async def test_embed_task_legacy_flat_file_null_pages(db, tmp_path, fake_embeddings):
    text_file = tmp_path / "legacy.json"
    text_file.write_text(json.dumps({"markdown": "flat " * 400}), encoding="utf-8")

    product = Product(
        file_path="/x/l.pdf", file_name="l.pdf", file_hash="embed-pages-2",
        title="Legacy Book", text_extracted=True,
        extracted_text_path=str(text_file),
    )
    db.add(product)
    await db.commit()

    ok = await queue_processor.handle_embed_task(db, product)
    assert ok is True

    rows = (await db.execute(
        select(ProductEmbedding).where(ProductEmbedding.product_id == product.id)
    )).scalars().all()
    assert rows
    assert all(r.page_start is None and r.page_end is None for r in rows)
```

Note: `handle_embed_task` calls `generate_embeddings` via a module-level import inside the function body (`from grimoire.services.embeddings import generate_embeddings`), so the monkeypatch on `grimoire.services.embeddings.generate_embeddings` is the one that matters — the fixture patches both to be safe.

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_embed_pages.py -v`
Expected: FAIL — `page_start` is None on content chunks (pages not yet wired), so `assert content[0].page_start == 1` fails.

- [ ] **Step 3: Rewire `handle_embed_task`**

In `backend/grimoire/services/queue_processor.py`, `handle_embed_task`:

Change the import line (451) to include the new builder:

```python
    from grimoire.services.embeddings import generate_embeddings, build_metadata_preamble, build_chunks_for_product
```

Change `_read_extracted_text` (lines 464–477) to also return pages:

```python
    def _read_extracted_text(path: str) -> tuple[str | None, list[dict] | None]:
        import json
        from pathlib import Path
        text_path = Path(path)
        if not text_path.exists():
            return None, None
        try:
            with open(text_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("markdown"), data.get("pages")
        except Exception:
            return None, None

    text, pages = await asyncio.to_thread(_read_extracted_text, extracted_text_path)
```

Replace the preamble-prepend + chunking block (lines 484–491):

```python
    # Prepend metadata so embeddings capture game system, publisher, etc.
    preamble = build_metadata_preamble(product)
    text = preamble + text

    # Chunk and embed BEFORE touching the DB to avoid holding a write
    # transaction open during the slow Ollama/OpenAI call.
    chunks = chunk_text(text, 500, 50)
    embeddings = await generate_embeddings(chunks)
```

with:

```python
    # Metadata preamble becomes its own leading chunk(s); content chunks carry
    # page anchors when the extraction JSON has them.
    preamble = build_metadata_preamble(product)
    chunk_tuples = build_chunks_for_product(preamble, pages, text)

    # Chunk and embed BEFORE touching the DB to avoid holding a write
    # transaction open during the slow Ollama/OpenAI call.
    embeddings = await generate_embeddings([c for c, _, _ in chunk_tuples])
```

(Remove `chunk_text` from the function's import line if now unused there.)

Replace the record-creation loop (lines 498–507):

```python
    for i, ((chunk, page_start, page_end), emb_result) in enumerate(zip(chunk_tuples, embeddings)):
        embedding_record = ProductEmbedding(
            product_id=product.id,
            chunk_index=i,
            chunk_text=chunk[:1000],
            embedding_model=emb_result.model,
            embedding_dim=len(emb_result.embedding),
            page_start=page_start,
            page_end=page_end,
        )
        embedding_record.set_embedding_vector(emb_result.embedding)
        db.add(embedding_record)
```

- [ ] **Step 4: Rewire `embed_product` and `embed_batch` routes**

In `backend/grimoire/api/routes/semantic.py`, `embed_product` (lines 175–211): replace the text/preamble/chunk/store section:

```python
    text = get_extracted_text(product)
    if not text:
        raise HTTPException(
            status_code=400,
            detail="Product has no extracted text"
        )

    from grimoire.services.processor import get_extracted_pages
    from grimoire.services.embeddings import build_metadata_preamble, build_chunks_for_product
    pages = get_extracted_pages(product)
    preamble = build_metadata_preamble(product)
    chunk_tuples = build_chunks_for_product(
        preamble, pages, text, request.chunk_size, request.overlap
    )

    # Delete existing embeddings
    await db.execute(
        delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id)
    )

    # Generate embeddings
    try:
        embeddings = await generate_embeddings(
            [c for c, _, _ in chunk_tuples], request.provider, request.model
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Store embeddings
    for i, ((chunk, page_start, page_end), emb_result) in enumerate(zip(chunk_tuples, embeddings)):
        embedding_record = ProductEmbedding(
            product_id=product_id,
            chunk_index=i,
            chunk_text=chunk[:1000],  # Store truncated for reference
            embedding_model=emb_result.model,
            embedding_dim=len(emb_result.embedding),
            page_start=page_start,
            page_end=page_end,
        )
        embedding_record.set_embedding_vector(emb_result.embedding)
        db.add(embedding_record)
```

Also update the trailing response `"chunks_embedded": len(chunks)` → `len(chunk_tuples)`.

Apply the same transformation inside `embed_batch` (lines 411–434): read `pages = get_extracted_pages(product)`, build `chunk_tuples = build_chunks_for_product(build_metadata_preamble(product), pages, text, chunk_size, 100)`, embed `[c for c, _, _ in chunk_tuples]`, store with `page_start`/`page_end`. Note `embed_batch` today does NOT prepend the preamble — adding it here makes the three paths consistent (deliberate fix, mention in commit).

- [ ] **Step 5: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_embed_pages.py tests/ -v --timeout=300 -q` (drop `--timeout` if pytest-timeout is not installed)
Expected: new tests PASS; no new failures vs baseline.

- [ ] **Step 6: Commit — Phase 0 complete**

```bash
git add backend/grimoire/services/queue_processor.py backend/grimoire/api/routes/semantic.py backend/tests/services/test_embed_pages.py
git commit -m "feat(embed): all embed paths store page-anchored chunks (Phase 0 complete - mass re-embed may proceed after merge)"
```

---

### Task 5: Query interpreter service

**Files:**
- Create: `backend/grimoire/services/query_interpreter.py`
- Test: `backend/tests/services/test_query_interpreter.py` (create)

**Interfaces:**
- Consumes: `get_setting_from_db` from `grimoire.processors.ai_identifier` (existing key lookup); `Product.game_system` / `Product.product_type` distinct values.
- Produces (used by Task 7):
  - `@dataclass Interpretation`: fields `semantic_query: str`, `level_min: int | None`, `level_max: int | None`, `game_system: str | None`, `product_type: str | None`, `source: str` (`"heuristic"` or `"llm"`); method `to_dict() -> dict`; property `has_filters -> bool`.
  - `interpret_heuristic(query: str, known_systems: list[str], known_types: list[str]) -> Interpretation` — pure, synchronous.
  - `async interpret_query(db, query: str) -> Interpretation` — loads known values, runs heuristics, optionally refines via LLM (validated, 5s timeout, per-query in-process cache).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_query_interpreter.py`:

```python
"""Heuristic query interpretation: levels, systems, types, stripping."""
import pytest

from grimoire.services.query_interpreter import (
    Interpretation,
    _validate_llm_result,
    interpret_heuristic,
)

SYSTEMS = ["D&D 5E", "Pathfinder 2E", "Dungeon Crawl Classics", "OSR"]
TYPES = ["Adventure", "Sourcebook", "Bestiary", "Setting", "Art/Maps"]


@pytest.mark.parametrize("query,lmin,lmax", [
    ("Undead adventure for 3rd level characters", 3, 3),
    ("undead adventure level 3", 3, 3),
    ("dungeon crawl levels 2-4", 2, 4),
    ("wilderness levels 5 to 7", 5, 7),
    ("funnel adventure for level 0 characters", 0, 0),
    ("swamp horror", None, None),
])
def test_level_extraction(query, lmin, lmax):
    r = interpret_heuristic(query, SYSTEMS, TYPES)
    assert r.level_min == lmin
    assert r.level_max == lmax


def test_level_phrase_stripped_from_semantic_query():
    r = interpret_heuristic("Undead adventure for 3rd level characters", SYSTEMS, TYPES)
    assert "3rd" not in r.semantic_query
    assert "level" not in r.semantic_query.lower()
    assert "undead" in r.semantic_query.lower()
    assert "adventure" in r.semantic_query.lower()  # topical word kept


def test_game_system_alias_dcc():
    r = interpret_heuristic("dcc funnel adventure", SYSTEMS, TYPES)
    assert r.game_system == "Dungeon Crawl Classics"
    assert "dcc" not in r.semantic_query.lower()


def test_game_system_full_name_match():
    r = interpret_heuristic("pathfinder 2e bestiary of dragons", SYSTEMS, TYPES)
    assert r.game_system == "Pathfinder 2E"


def test_product_type_keyword_sets_filter_but_stays_in_query():
    r = interpret_heuristic("undead adventure", SYSTEMS, TYPES)
    assert r.product_type == "Adventure"
    assert "adventure" in r.semantic_query.lower()


def test_unknown_system_not_invented():
    r = interpret_heuristic("shadowdark ruins", SYSTEMS, TYPES)
    assert r.game_system is None


def test_semantic_query_never_empty():
    r = interpret_heuristic("level 3", SYSTEMS, TYPES)
    assert r.semantic_query.strip()  # falls back to the original query


def test_validate_llm_result_clamps_and_drops():
    base = Interpretation(semantic_query="orig")
    out = _validate_llm_result(
        {"level_min": -5, "level_max": 99, "game_system": "Nonsense RPG",
         "product_type": "Adventure", "semantic_query": "undead crypts"},
        base, SYSTEMS, TYPES,
    )
    assert out.level_min == 0
    assert out.level_max == 30
    assert out.game_system is None       # not a known value -> dropped
    assert out.product_type == "Adventure"
    assert out.semantic_query == "undead crypts"
    assert out.source == "llm"


def test_validate_llm_result_empty_semantic_query_keeps_heuristic():
    base = Interpretation(semantic_query="orig words")
    out = _validate_llm_result({"semantic_query": "  "}, base, SYSTEMS, TYPES)
    assert out.semantic_query == "orig words"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_query_interpreter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grimoire.services.query_interpreter'`.

- [ ] **Step 3: Implement the service**

Create `backend/grimoire/services/query_interpreter.py`:

```python
"""Interpret natural-language library queries into filters + a refined
semantic query.

Heuristic regex pass always runs (zero latency, no dependencies). If an
Anthropic or OpenAI key is configured, an LLM pass refines the result; any
failure or timeout falls back to the heuristic interpretation. Search never
blocks on LLM availability.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, asdict

import httpx

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 5.0
ANTHROPIC_MODEL = "claude-haiku-4-5"
OPENAI_MODEL = "gpt-4o-mini"


@dataclass
class Interpretation:
    semantic_query: str
    level_min: int | None = None
    level_max: int | None = None
    game_system: str | None = None
    product_type: str | None = None
    source: str = "heuristic"

    @property
    def has_filters(self) -> bool:
        return any(
            v is not None
            for v in (self.level_min, self.level_max, self.game_system, self.product_type)
        )

    def to_dict(self) -> dict:
        return asdict(self)


# --- Heuristic pass -------------------------------------------------------

# Order matters: ranges before single levels; "for Nth level characters"
# before bare "Nth level" so the whole phrase is stripped.
_LEVEL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bfor\s+(\d{1,2})(?:st|nd|rd|th)?\s*[- ]?level\s+(?:characters?|pcs?|players?)\b", re.I), "single"),
    (re.compile(r"\blevels?\s+(\d{1,2})\s*(?:-|–|—|\bto\b)\s*(\d{1,2})\b", re.I), "range"),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\s*[- ]?level\b", re.I), "single"),
    (re.compile(r"\blevels?\s+(\d{1,2})\b", re.I), "single"),
]

# Curated aliases mapped onto substrings of known DB game_system values.
# Key: phrase in the query; value: substring to find in a known system name.
_SYSTEM_ALIASES: dict[str, str] = {
    "dcc": "dungeon crawl",
    "dungeon crawl classics": "dungeon crawl",
    "5e": "5e",
    "fifth edition": "5e",
    "d&d": "d&d",
    "dnd": "d&d",
    "pf2e": "pathfinder 2",
    "pf2": "pathfinder 2",
    "pathfinder 2e": "pathfinder 2",
    "pathfinder": "pathfinder",
    "osr": "osr",
    "call of cthulhu": "cthulhu",
    "coc": "cthulhu",
}

# Query keyword -> product_type value (validated against known values).
# These words stay in the semantic query — they carry topical meaning too.
_TYPE_KEYWORDS: dict[str, str] = {
    "adventure": "Adventure",
    "module": "Adventure",
    "sourcebook": "Sourcebook",
    "bestiary": "Bestiary",
    "monster manual": "Bestiary",
    "setting": "Setting",
}


def _clamp_level(v) -> int | None:
    try:
        return max(0, min(30, int(v)))
    except (TypeError, ValueError):
        return None


def interpret_heuristic(
    query: str, known_systems: list[str], known_types: list[str]
) -> Interpretation:
    """Regex/alias interpretation. Pure and synchronous."""
    result = Interpretation(semantic_query=query)
    working = query

    # Levels — first matching pattern wins; strip the matched phrase.
    for pattern, kind in _LEVEL_PATTERNS:
        m = pattern.search(working)
        if m:
            if kind == "range":
                result.level_min = _clamp_level(m.group(1))
                result.level_max = _clamp_level(m.group(2))
            else:
                result.level_min = result.level_max = _clamp_level(m.group(1))
            working = (working[: m.start()] + " " + working[m.end():]).strip()
            break

    # Game system — known value verbatim first, then curated aliases. Longest
    # phrases first so "dungeon crawl classics" beats "dcc"-style prefixes.
    lowered = working.lower()
    matched_system_phrase: str | None = None
    for system in sorted(known_systems, key=len, reverse=True):
        s = (system or "").strip()
        if s and re.search(rf"\b{re.escape(s.lower())}\b", lowered):
            result.game_system = system
            matched_system_phrase = s.lower()
            break
    if result.game_system is None:
        for alias in sorted(_SYSTEM_ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                target = _SYSTEM_ALIASES[alias]
                hit = next(
                    (s for s in known_systems if s and target in s.lower()), None
                )
                if hit:
                    result.game_system = hit
                    matched_system_phrase = alias
                    break
    if matched_system_phrase:
        working = re.sub(
            rf"\b{re.escape(matched_system_phrase)}\b", " ", working, flags=re.I
        ).strip()

    # Product type — sets the filter but the keyword STAYS in the query
    # ("adventure" is topical as well as categorical).
    lowered = working.lower()
    for keyword in sorted(_TYPE_KEYWORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            candidate = _TYPE_KEYWORDS[keyword]
            hit = next(
                (t for t in known_types if t and t.lower() == candidate.lower()), None
            )
            if hit:
                result.product_type = hit
                break

    working = re.sub(r"\s{2,}", " ", working).strip(" ,.-")
    result.semantic_query = working if working else query
    return result


# --- LLM refinement -------------------------------------------------------

_LLM_PROMPT = """You are a search query interpreter for a tabletop-RPG PDF library.

Convert the user's query into structured search parameters. Return ONLY a JSON object:
{{"level_min": int or null, "level_max": int or null,
  "game_system": string or null, "product_type": string or null,
  "semantic_query": "query text optimized for semantic search over book content"}}

game_system must be one of: {systems}
product_type must be one of: {types}
Use null when the query does not clearly imply a value. Keep topical words
(monsters, themes, environments) in semantic_query.

User query: {query}"""

# Tiny in-process cache: query string -> validated Interpretation
_llm_cache: dict[str, Interpretation] = {}
_LLM_CACHE_MAX = 256


def _validate_llm_result(
    data: dict,
    heuristic: Interpretation,
    known_systems: list[str],
    known_types: list[str],
) -> Interpretation:
    """Merge validated LLM output over the heuristic result. Unknown
    game_system/product_type values are dropped; levels clamped to 0-30;
    empty semantic_query keeps the heuristic one."""
    out = Interpretation(**{**heuristic.to_dict(), "source": "llm"})

    if "level_min" in data:
        out.level_min = _clamp_level(data.get("level_min"))
    if "level_max" in data:
        out.level_max = _clamp_level(data.get("level_max"))

    system = data.get("game_system")
    if isinstance(system, str):
        hit = next((s for s in known_systems if s and s.lower() == system.lower()), None)
        out.game_system = hit if hit else out.game_system
        if hit is None and system:
            out.game_system = heuristic.game_system  # never invent values
    ptype = data.get("product_type")
    if isinstance(ptype, str):
        hit = next((t for t in known_types if t and t.lower() == ptype.lower()), None)
        if hit:
            out.product_type = hit

    sq = data.get("semantic_query")
    if isinstance(sq, str) and sq.strip():
        out.semantic_query = sq.strip()
    return out


async def _call_llm(prompt: str) -> dict | None:
    """One LLM call, Anthropic preferred, OpenAI fallback. None on any failure."""
    from grimoire.processors.ai_identifier import get_setting_from_db

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "") or (
        await get_setting_from_db("anthropic_api_key") or ""
    )
    openai_key = os.getenv("OPENAI_API_KEY", "") or (
        await get_setting_from_db("openai_api_key") or ""
    )
    if not anthropic_key and not openai_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            if anthropic_key:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": ANTHROPIC_MODEL,
                        "max_tokens": 300,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                content = resp.json()["content"][0]["text"].strip()
            else:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": OPENAI_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]

        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1:
            return None
        return json.loads(content[start:end + 1])
    except Exception as e:
        logger.warning("LLM query interpretation failed, using heuristics: %s", e)
        return None


async def _get_known_values(db) -> tuple[list[str], list[str]]:
    from sqlalchemy import select
    from grimoire.models import Product

    systems = [
        s for s in (await db.execute(
            select(Product.game_system).distinct().where(Product.game_system.isnot(None))
        )).scalars().all() if s
    ]
    types = [
        t for t in (await db.execute(
            select(Product.product_type).distinct().where(Product.product_type.isnot(None))
        )).scalars().all() if t
    ]
    return systems, types


async def interpret_query(db, query: str) -> Interpretation:
    """Full interpretation: heuristics always; LLM refinement when a key is
    configured (validated, cached per query, 5s timeout, silent fallback)."""
    known_systems, known_types = await _get_known_values(db)
    heuristic = interpret_heuristic(query, known_systems, known_types)

    cached = _llm_cache.get(query)
    if cached is not None:
        return cached

    data = await _call_llm(_LLM_PROMPT.format(
        systems=", ".join(known_systems[:50]) or "(none)",
        types=", ".join(known_types[:20]) or "(none)",
        query=query,
    ))
    if data is None:
        return heuristic

    result = _validate_llm_result(data, heuristic, known_systems, known_types)
    if len(_llm_cache) >= _LLM_CACHE_MAX:
        _llm_cache.clear()
    _llm_cache[query] = result
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_query_interpreter.py -v`
Expected: PASS (all cases). Iterate on the regexes until the table-driven cases pass — the tests define the contract.

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/query_interpreter.py backend/tests/services/test_query_interpreter.py
git commit -m "feat(search): query interpreter - heuristic level/system/type extraction + optional LLM refinement"
```

---

### Task 6: Search service primitives — SV cache, chunk scorer, candidate union

**Files:**
- Create: `backend/grimoire/services/search_service.py` (primitives half)
- Modify: `backend/grimoire/services/embeddings.py` (invalidation callback registry on `invalidate_vector_cache`, line 331)
- Test: `backend/tests/services/test_search_service.py` (create)

**Interfaces:**
- Consumes: `ProductSearchVector`, `ProductEmbedding`, `invalidate_vector_cache`.
- Produces (used by Task 7):
  - In `embeddings.py`: `register_invalidation_callback(fn: Callable[[], None]) -> None`; `invalidate_vector_cache()` now also runs registered callbacks.
  - In `search_service.py`:
    - `async get_sv_index(db) -> tuple[list[int], "np.ndarray | None"]` — cached (ids, float32 matrix) of all ProductSearchVectors; `(ids, None)` when empty.
    - `sv_top_candidates(query_vector, ids, matrix, allowed_ids, limit) -> list[tuple[int, float]]` — cosine top-N restricted to `allowed_ids` (None = unrestricted), no threshold.
    - `chunk_score(similarities: "np.ndarray", top_k: int = TOP_K_CHUNKS) -> float` — mean of top-k sims (max-pool if fewer than k).
    - `async load_candidate_chunks(db, product_ids, query_dim) -> dict[int, tuple["np.ndarray", list[tuple[str, int | None]]]]` — per-product `(matrix, [(chunk_text, page_start), ...])`, dimension-filtered, LRU-cached per (product_id, dim).
    - `rerank_by_chunks(query_vector, per_product) -> list[tuple[int, float, str, int | None]]` — `(product_id, score, best_chunk_text, best_page)` sorted desc.
    - `merge_candidates(sv_list, bm25_list, cap=MAX_CANDIDATES) -> list[int]` — all SV candidates, remainder filled from BM25 rank order, deduped.
    - Module constants from Global Constraints.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_search_service.py`:

```python
"""Search service primitives: scoring, candidate merge, caches."""
import numpy as np
import pytest
from sqlalchemy import delete

from grimoire.models import Product, ProductEmbedding
from grimoire.models.product_search_vector import ProductSearchVector
from grimoire.services import search_service
from grimoire.services.embeddings import invalidate_vector_cache
from grimoire.services.search_service import (
    chunk_score,
    merge_candidates,
    rerank_by_chunks,
    sv_top_candidates,
)


def test_chunk_score_top3_mean():
    sims = np.array([0.9, 0.1, 0.8, 0.7, 0.2])
    assert chunk_score(sims, top_k=3) == pytest.approx((0.9 + 0.8 + 0.7) / 3)


def test_chunk_score_fewer_than_k_uses_all():
    assert chunk_score(np.array([0.6, 0.4]), top_k=3) == pytest.approx(0.5)


def test_sv_top_candidates_restricts_and_ranks():
    ids = [1, 2, 3]
    matrix = np.array([[1, 0], [0, 1], [0.9, 0.1]], dtype=np.float32)
    query = [1.0, 0.0]
    out = sv_top_candidates(query, ids, matrix, allowed_ids={1, 3}, limit=10)
    assert [pid for pid, _ in out] == [1, 3]  # 2 filtered out; ranked by cosine
    out_all = sv_top_candidates(query, ids, matrix, allowed_ids=None, limit=2)
    assert len(out_all) == 2 and out_all[0][0] == 1


def test_merge_candidates_sv_first_then_bm25_fill():
    sv = [(1, 0.9), (2, 0.8)]
    bm25 = [(2, 5.0), (3, 4.0), (4, 3.0)]
    assert merge_candidates(sv, bm25, cap=3) == [1, 2, 3]


def test_rerank_by_chunks_orders_and_reports_best_chunk():
    q = [1.0, 0.0]
    per_product = {
        7: (np.array([[0.1, 0.9], [0.95, 0.05]], dtype=np.float32),
            [("weak chunk", None), ("strong chunk", 12)]),
        8: (np.array([[0.5, 0.5]], dtype=np.float32), [("meh", 3)]),
    }
    ranked = rerank_by_chunks(q, per_product)
    assert ranked[0][0] == 7
    assert ranked[0][2] == "strong chunk"
    assert ranked[0][3] == 12


async def test_sv_index_cached_and_invalidated(db):
    # unique products for this test
    p1 = Product(file_path="/x/sv1.pdf", file_name="sv1.pdf", file_hash="svc-1")
    p2 = Product(file_path="/x/sv2.pdf", file_name="sv2.pdf", file_hash="svc-2")
    db.add_all([p1, p2])
    await db.commit()

    for p, vec in [(p1, [1.0, 0.0]), (p2, [0.0, 1.0])]:
        sv = ProductSearchVector(product_id=p.id, embedding_model="fake", embedding_dim=2)
        sv.set_vector(vec)
        db.add(sv)
    await db.commit()

    invalidate_vector_cache()  # start clean
    ids, matrix = await search_service.get_sv_index(db)
    assert p1.id in ids and p2.id in ids

    # add another SV; cached index must NOT see it until invalidation
    p3 = Product(file_path="/x/sv3.pdf", file_name="sv3.pdf", file_hash="svc-3")
    db.add(p3)
    await db.commit()
    sv3 = ProductSearchVector(product_id=p3.id, embedding_model="fake", embedding_dim=2)
    sv3.set_vector([0.5, 0.5])
    db.add(sv3)
    await db.commit()

    ids2, _ = await search_service.get_sv_index(db)
    assert p3.id not in ids2  # served from cache
    invalidate_vector_cache()
    ids3, _ = await search_service.get_sv_index(db)
    assert p3.id in ids3  # callback cleared the cache

    # cleanup so other tests' SV counts aren't polluted
    await db.execute(delete(ProductSearchVector).where(
        ProductSearchVector.product_id.in_([p1.id, p2.id, p3.id])))
    await db.commit()
    invalidate_vector_cache()


async def test_load_candidate_chunks_filters_dimension(db):
    p = Product(file_path="/x/ch1.pdf", file_name="ch1.pdf", file_hash="svc-ch-1")
    db.add(p)
    await db.commit()

    good = ProductEmbedding(product_id=p.id, chunk_index=0, chunk_text="good",
                            embedding_model="fake", embedding_dim=2, page_start=4, page_end=4)
    good.set_embedding_vector([1.0, 0.0])
    stale = ProductEmbedding(product_id=p.id, chunk_index=1, chunk_text="stale",
                             embedding_model="old", embedding_dim=3)
    stale.set_embedding_vector([1.0, 0.0, 0.0])
    db.add_all([good, stale])
    await db.commit()

    invalidate_vector_cache()
    per = await search_service.load_candidate_chunks(db, [p.id], query_dim=2)
    matrix, meta = per[p.id]
    assert matrix.shape == (1, 2)          # stale 3-dim chunk excluded
    assert meta == [("good", 4)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_search_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grimoire.services.search_service'`.

- [ ] **Step 3: Add the invalidation callback registry**

In `backend/grimoire/services/embeddings.py`, replace `invalidate_vector_cache` (lines 331–334):

```python
_invalidation_callbacks: list = []


def register_invalidation_callback(fn) -> None:
    """Register a zero-arg callable run whenever embeddings change."""
    _invalidation_callbacks.append(fn)


def invalidate_vector_cache():
    """Call when embeddings are added/removed."""
    global _vector_cache
    _vector_cache = None
    for fn in _invalidation_callbacks:
        fn()
```

- [ ] **Step 4: Implement the primitives**

Create `backend/grimoire/services/search_service.py`:

```python
"""Two-stage semantic search: candidate union (averaged vectors + BM25) then
chunk-level re-rank. See docs/superpowers/specs/2026-07-08-search-accuracy-design.md.
"""

import logging
from collections import OrderedDict

import numpy as np
from sqlalchemy import select

from grimoire.models import Product, ProductEmbedding
from grimoire.models.product_search_vector import ProductSearchVector
from grimoire.services.embeddings import register_invalidation_callback

logger = logging.getLogger(__name__)

# Tunable retrieval constants (adjust via the eval harness, Task 11)
CANDIDATES_PER_SOURCE = 150
MAX_CANDIDATES = 200
TOP_K_CHUNKS = 3
CHUNK_SCORE_THRESHOLD = 0.45
SEMANTIC_RRF_WEIGHT = 1.0
KEYWORD_RRF_WEIGHT = 1.0

# --- Caches ----------------------------------------------------------------

_sv_index: tuple[list[int], np.ndarray | None] | None = None
_chunk_cache: OrderedDict = OrderedDict()  # (product_id, dim) -> (matrix, meta)
_CHUNK_CACHE_MAX = 300


def _clear_caches() -> None:
    global _sv_index
    _sv_index = None
    _chunk_cache.clear()


register_invalidation_callback(_clear_caches)


async def get_sv_index(db) -> tuple[list[int], np.ndarray | None]:
    """All product search vectors as (ids, float32 matrix), cached in memory.

    ~12.7k x 768 floats is ~39 MB — cheap to hold, expensive to reload from
    SQLite per search (which is what the old route did).
    """
    global _sv_index
    if _sv_index is not None:
        return _sv_index

    result = await db.execute(select(ProductSearchVector))
    svs = result.scalars().all()
    if not svs:
        _sv_index = ([], None)
        return _sv_index

    # Group by dim, keep the dominant dimension (mixed models mid-re-embed)
    ids = [sv.product_id for sv in svs]
    vectors = [sv.get_vector() for sv in svs]
    dims = [len(v) for v in vectors]
    dominant = max(set(dims), key=dims.count)
    filtered = [(i, v) for i, v, d in zip(ids, vectors, dims) if d == dominant]
    ids = [i for i, _ in filtered]
    matrix = np.array([v for _, v in filtered], dtype=np.float32)
    _sv_index = (ids, matrix)
    return _sv_index


def sv_top_candidates(
    query_vector: list[float],
    ids: list[int],
    matrix: np.ndarray | None,
    allowed_ids: set[int] | None,
    limit: int,
) -> list[tuple[int, float]]:
    """Cosine top-N over the SV matrix, restricted to allowed_ids. No threshold."""
    if matrix is None or not ids or matrix.shape[1] != len(query_vector):
        return []

    q = np.array(query_vector, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(q)
    norms[norms == 0] = 1e-10
    sims = matrix @ q / norms

    pairs = (
        (pid, float(s)) for pid, s in zip(ids, sims)
        if allowed_ids is None or pid in allowed_ids
    )
    return sorted(pairs, key=lambda x: x[1], reverse=True)[:limit]


def chunk_score(similarities: np.ndarray, top_k: int = TOP_K_CHUNKS) -> float:
    """Product relevance from its chunk similarities: mean of the top-k
    (all of them when fewer than k). Rewards focused topical hits without
    letting one noisy chunk dominate."""
    if similarities.size == 0:
        return 0.0
    k = min(top_k, similarities.size)
    top = np.partition(similarities, -k)[-k:]
    return float(np.mean(top))


async def load_candidate_chunks(
    db, product_ids: list[int], query_dim: int
) -> dict[int, tuple[np.ndarray, list[tuple[str, int | None]]]]:
    """Chunk vectors for candidate products only, dimension-filtered, with a
    bounded LRU cache keyed by (product_id, dim). meta is [(chunk_text,
    page_start), ...] aligned with matrix rows."""
    out: dict[int, tuple[np.ndarray, list[tuple[str, int | None]]]] = {}
    missing: list[int] = []
    for pid in product_ids:
        key = (pid, query_dim)
        if key in _chunk_cache:
            _chunk_cache.move_to_end(key)
            out[pid] = _chunk_cache[key]
        else:
            missing.append(pid)

    if missing:
        result = await db.execute(
            select(ProductEmbedding).where(
                ProductEmbedding.product_id.in_(missing),
                ProductEmbedding.embedding_dim == query_dim,
            )
        )
        rows_by_pid: dict[int, list[ProductEmbedding]] = {}
        for row in result.scalars().all():
            rows_by_pid.setdefault(row.product_id, []).append(row)

        for pid in missing:
            rows = rows_by_pid.get(pid, [])
            if rows:
                matrix = np.array(
                    [r.get_embedding_vector() for r in rows], dtype=np.float32
                )
                meta = [(r.chunk_text, r.page_start) for r in rows]
            else:
                matrix = np.empty((0, query_dim), dtype=np.float32)
                meta = []
            entry = (matrix, meta)
            _chunk_cache[(pid, query_dim)] = entry
            while len(_chunk_cache) > _CHUNK_CACHE_MAX:
                _chunk_cache.popitem(last=False)
            out[pid] = entry

    return out


def rerank_by_chunks(
    query_vector: list[float],
    per_product: dict[int, tuple[np.ndarray, list[tuple[str, int | None]]]],
) -> list[tuple[int, float, str, int | None]]:
    """Score candidates by their best chunks. Returns (product_id, score,
    best_chunk_text, best_page) sorted by score desc. Products with no valid
    chunks are omitted (they can still surface via BM25)."""
    q = np.array(query_vector, dtype=np.float32)
    qn = np.linalg.norm(q)
    ranked = []
    for pid, (matrix, meta) in per_product.items():
        if matrix.shape[0] == 0:
            continue
        norms = np.linalg.norm(matrix, axis=1) * qn
        norms[norms == 0] = 1e-10
        sims = matrix @ q / norms
        best_idx = int(np.argmax(sims))
        ranked.append((pid, chunk_score(sims), meta[best_idx][0], meta[best_idx][1]))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def merge_candidates(
    sv_list: list[tuple[int, float]],
    bm25_list: list[tuple[int, float]],
    cap: int = MAX_CANDIDATES,
) -> list[int]:
    """Union of candidate sources: every SV candidate, remainder filled from
    BM25 in rank order, deduped, capped."""
    seen: set[int] = set()
    merged: list[int] = []
    for pid, _ in sv_list:
        if pid not in seen:
            seen.add(pid)
            merged.append(pid)
    for pid, _ in bm25_list:
        if len(merged) >= cap:
            break
        if pid not in seen:
            seen.add(pid)
            merged.append(pid)
    return merged[:cap]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_search_service.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/services/search_service.py backend/grimoire/services/embeddings.py backend/tests/services/test_search_service.py
git commit -m "feat(search): search service primitives - SV index cache, chunk scorer, candidate union"
```

---

### Task 7: Full search flow + route rewiring + delete dead `/semantic/query`

**Files:**
- Modify: `backend/grimoire/services/search_service.py` (add the `search()` orchestrator)
- Modify: `backend/grimoire/api/routes/semantic.py` (`SemanticSearchRequest` + `/search` handler lines 247–386; delete `/query` endpoint, `interpret_nl_query`, `NL_QUERY_PROMPT`, `NaturalLanguageQueryRequest` — lines 113–118 and 693–899)
- Test: `backend/tests/services/test_search_flow.py` (create)

**Interfaces:**
- Consumes: Task 5 `interpret_query`/`Interpretation`; Task 6 primitives; existing `search_fts`, `reciprocal_rank_fusion`, `build_semantic_filter_conditions`, `generate_embeddings`, `product_to_response`.
- Produces:
  - `SemanticSearchRequest` gains `interpret: bool = Field(True)`.
  - `async search_service.search(db, request: SemanticSearchRequest) -> dict` — full response: `{"query", "results", "total_matches", "interpretation"}` where each result item = `product_to_response(...) | {"score", "matched_page", "snippet", "match_type"}`.
  - `/semantic/search` route = provider check + thin call into `search_service.search`.
  - `POST /semantic/query` is GONE (nothing in `frontend/src` calls it — verified by grep; confirm no backend test imports `interpret_nl_query` before deleting, and delete such tests if they only cover the removed endpoint).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_search_flow.py`:

```python
"""End-to-end search flow with fake embeddings + fake FTS."""
import json

import pytest
from sqlalchemy import delete

from grimoire.models import Product, ProductEmbedding
from grimoire.models.product_search_vector import ProductSearchVector
from grimoire.services import search_service
from grimoire.services.embeddings import EmbeddingResult, invalidate_vector_cache
from grimoire.api.routes.semantic import SemanticSearchRequest

DIM = 4
UNDEAD = [1.0, 0.0, 0.0, 0.0]
DRAGON = [0.0, 1.0, 0.0, 0.0]
BLAND = [0.5, 0.5, 0.5, 0.5]


async def _mk_product(db, hash_, title, level_min=None, level_max=None,
                      sv_vec=None, chunks=()):
    p = Product(file_path=f"/x/{hash_}.pdf", file_name=f"{hash_}.pdf",
                file_hash=hash_, title=title,
                level_range_min=level_min, level_range_max=level_max)
    db.add(p)
    await db.commit()
    if sv_vec is not None:
        sv = ProductSearchVector(product_id=p.id, embedding_model="fake",
                                 embedding_dim=DIM)
        sv.set_vector(sv_vec)
        db.add(sv)
    for i, (text, vec, page) in enumerate(chunks):
        e = ProductEmbedding(product_id=p.id, chunk_index=i, chunk_text=text,
                             embedding_model="fake", embedding_dim=DIM,
                             page_start=page, page_end=page)
        e.set_embedding_vector(vec)
        db.add(e)
    await db.commit()
    return p


@pytest.fixture
def fake_search_env(monkeypatch):
    """Query embeds to UNDEAD; FTS returns nothing unless a test overrides."""
    async def fake_embed(texts, provider=None, model=None):
        return [EmbeddingResult(embedding=UNDEAD, model="fake") for _ in texts]

    async def fake_fts(db, query, game_system=None, product_type=None, limit=20):
        return []

    monkeypatch.setattr(search_service, "generate_embeddings", fake_embed)
    monkeypatch.setattr(search_service, "search_fts", fake_fts)
    # avoid real settings lookup / LLM
    from grimoire.services.query_interpreter import Interpretation

    async def fake_interpret(db, query):
        return Interpretation(semantic_query=query, level_min=3, level_max=3,
                              source="heuristic")

    monkeypatch.setattr(search_service, "interpret_query", fake_interpret)
    invalidate_vector_cache()
    yield
    invalidate_vector_cache()


async def test_chunk_rerank_beats_diluted_average(db, fake_search_env):
    # Book A: bland average but one strongly-undead chunk -> should win
    a = await _mk_product(db, "flow-a", "Tome of Many Things", sv_vec=BLAND, chunks=[
        ("boring intro", DRAGON, 1),
        ("the undead crypt of horrors", UNDEAD, 47),
    ])
    # Book B: average closer to query but weak chunks
    b = await _mk_product(db, "flow-b", "Generic Fantasy", sv_vec=[0.8, 0.2, 0.2, 0.2],
                          chunks=[("mild spooky content", [0.6, 0.4, 0.4, 0.4], 2)])

    req = SemanticSearchRequest(query="undead adventure", top_k=5, interpret=True, hybrid=True)
    out = await search_service.search(db, req)

    ids = [r["id"] for r in out["results"]]
    assert ids.index(a.id) < ids.index(b.id)
    top = out["results"][0]
    assert top["matched_page"] == 47
    assert "undead crypt" in top["snippet"]
    assert top["match_type"] in ("semantic", "both")
    assert out["interpretation"]["level_min"] == 3


async def test_lenient_interpreted_level_filter_keeps_nulls(db, fake_search_env):
    # level 10 product excluded; NULL-level product kept (lenient semantics)
    high = await _mk_product(db, "flow-high", "Epic Level 10", 10, 12,
                             sv_vec=UNDEAD, chunks=[("undead epic", UNDEAD, 1)])
    unlabeled = await _mk_product(db, "flow-null", "Mystery Book", None, None,
                                  sv_vec=UNDEAD, chunks=[("undead mystery", UNDEAD, 1)])

    req = SemanticSearchRequest(query="undead for 3rd level", top_k=10, interpret=True)
    out = await search_service.search(db, req)
    ids = [r["id"] for r in out["results"]]
    assert unlabeled.id in ids
    assert high.id not in ids


async def test_bm25_only_product_survives_without_valid_chunks(db, fake_search_env, monkeypatch):
    # Product with no chunks at all (mid re-embed) surfaces via keyword rank
    kw = await _mk_product(db, "flow-kw", "Undead Keyword Hit")

    async def fts_hit(db_, query, game_system=None, product_type=None, limit=20):
        return [{"id": kw.id, "relevance_score": 9.9}]

    monkeypatch.setattr(search_service, "search_fts", fts_hit)
    req = SemanticSearchRequest(query="undead", top_k=10, interpret=False)
    out = await search_service.search(db, req)
    ids = [r["id"] for r in out["results"]]
    assert kw.id in ids
    item = next(r for r in out["results"] if r["id"] == kw.id)
    assert item["match_type"] == "keyword"


async def test_interpret_false_skips_interpretation(db, fake_search_env):
    req = SemanticSearchRequest(query="undead for 3rd level", top_k=5, interpret=False)
    out = await search_service.search(db, req)
    assert out["interpretation"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_search_flow.py -v`
Expected: FAIL — `SemanticSearchRequest` has no field `interpret` / `search_service` has no attribute `search`.

- [ ] **Step 3: Add the orchestrator to `search_service.py`**

Append to `backend/grimoire/services/search_service.py`:

```python
# --- Full search flow --------------------------------------------------------

from grimoire.services.embeddings import generate_embeddings  # noqa: E402
from grimoire.services.fts_service import search_fts  # noqa: E402
from grimoire.services.hybrid_search import reciprocal_rank_fusion  # noqa: E402
from grimoire.services.query_interpreter import Interpretation, interpret_query  # noqa: E402


def build_interpreted_conditions(interp: Interpretation) -> list:
    """Lenient conditions for interpreter-derived filters: (== value) OR NULL.
    A misparse or unlabeled product must not vanish silently. Explicit
    FilterDrawer filters stay strict (build_semantic_filter_conditions)."""
    conditions = []
    if interp.game_system:
        conditions.append(
            (Product.game_system == interp.game_system) | (Product.game_system.is_(None))
        )
    if interp.product_type:
        conditions.append(
            (Product.product_type == interp.product_type) | (Product.product_type.is_(None))
        )
    if interp.level_min is not None:
        conditions.append(
            (Product.level_range_max >= interp.level_min) | (Product.level_range_max.is_(None))
        )
    if interp.level_max is not None:
        conditions.append(
            (Product.level_range_min <= interp.level_max) | (Product.level_range_min.is_(None))
        )
    return conditions


async def _allowed_ids(db, conditions: list, request) -> set[int] | None:
    """Evaluate filters SQL-side once; None means unfiltered."""
    from grimoire.models import ProductTag

    extra = list(conditions)
    if request.tags:
        tag_ids = [int(t.strip()) for t in request.tags.split(",") if t.strip()]
        if tag_ids:
            tag_subq = select(ProductTag.product_id).where(ProductTag.tag_id.in_(tag_ids))
            extra.append(Product.id.in_(tag_subq))
    if request.collection:
        from grimoire.models.collection import CollectionProduct
        coll_subq = select(CollectionProduct.product_id).where(
            CollectionProduct.collection_id == request.collection
        )
        extra.append(Product.id.in_(coll_subq))

    if not extra:
        return None
    result = await db.execute(select(Product.id).where(*extra))
    return set(result.scalars().all())


async def search(db, request) -> dict:
    """Two-stage semantic search. request is a SemanticSearchRequest."""
    from sqlalchemy.orm import selectinload
    from grimoire.models import ProductTag
    from grimoire.api.routes.products import product_to_response
    from grimoire.api.routes.semantic import build_semantic_filter_conditions

    # 1. Interpret (explicit drawer filters win over interpreted ones)
    interp: Interpretation | None = None
    semantic_query = request.query
    if getattr(request, "interpret", True):
        interp = await interpret_query(db, request.query)
        if request.game_system:
            interp.game_system = None
        if request.product_type:
            interp.product_type = None
        if request.level_min is not None or request.level_max is not None:
            interp.level_min = None
            interp.level_max = None
        semantic_query = interp.semantic_query or request.query

    # 2. Pre-filter: strict explicit conditions + lenient interpreted ones
    conditions = build_semantic_filter_conditions(request)
    if interp is not None:
        conditions += build_interpreted_conditions(interp)
    allowed = await _allowed_ids(db, conditions, request)

    # 3. Embed the (refined) query
    query_embeddings = await generate_embeddings([semantic_query], None, request.model)
    query_vector = query_embeddings[0].embedding

    # 4. Stage 1 candidates: SV top-N union BM25 top-N
    ids, matrix = await get_sv_index(db)
    sv_candidates = sv_top_candidates(
        query_vector, ids, matrix, allowed, CANDIDATES_PER_SOURCE
    )

    keyword_ranking: list[tuple[int, float]] = []
    try:
        fts_results = await search_fts(
            db, semantic_query,
            game_system=request.game_system,
            product_type=request.product_type,
            limit=CANDIDATES_PER_SOURCE,
        )
        keyword_ranking = [
            (r["id"], r["relevance_score"]) for r in fts_results
            if allowed is None or r["id"] in allowed
        ]
    except Exception:
        logger.warning("FTS failed during search; continuing semantic-only")

    # Zero search vectors anywhere -> pure FTS fallback
    if matrix is None and not sv_candidates:
        candidate_ids = [pid for pid, _ in keyword_ranking]
        semantic_ranking: list[tuple[int, float, str, int | None]] = []
    else:
        candidate_ids = merge_candidates(sv_candidates, keyword_ranking)

        # 5. Stage 2: chunk-level re-rank over candidates only
        per_product = await load_candidate_chunks(db, candidate_ids, len(query_vector))
        reranked = rerank_by_chunks(query_vector, per_product)
        semantic_ranking = [r for r in reranked if r[1] >= CHUNK_SCORE_THRESHOLD]

    best_chunk = {pid: (text, page) for pid, _, text, page in semantic_ranking}

    # 6. Fuse chunk ranking with keyword ranking
    fused = reciprocal_rank_fusion(
        [(pid, score) for pid, score, _, _ in semantic_ranking],
        keyword_ranking,
        semantic_weight=SEMANTIC_RRF_WEIGHT,
        keyword_weight=KEYWORD_RRF_WEIGHT,
    )
    if fused and fused[0][1] > 0:
        top_score = fused[0][1]
        fused = [(pid, s / top_score) for pid, s in fused]

    semantic_ids = {pid for pid, *_ in semantic_ranking}
    keyword_ids = {pid for pid, _ in keyword_ranking}

    matched_ids = [pid for pid, _ in fused][: request.top_k]
    score_map = dict(fused)

    if not matched_ids:
        return {
            "query": request.query,
            "results": [],
            "total_matches": 0,
            "interpretation": interp.to_dict() if interp else None,
        }

    # 7. Hydrate products and build response items
    products_result = await db.execute(
        select(Product)
        .where(Product.id.in_(matched_ids))
        .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
    )
    products = {p.id: p for p in products_result.scalars().all()}

    results = []
    for pid in matched_ids:
        product = products.get(pid)
        if not product:
            continue
        item = product_to_response(product).model_dump()
        item["score"] = round(score_map[pid], 4)
        chunk_text, page = best_chunk.get(pid, (None, None))
        item["matched_page"] = page
        item["snippet"] = (
            chunk_text[:150] + "..." if chunk_text and len(chunk_text) > 150 else chunk_text
        )
        if pid in semantic_ids and pid in keyword_ids:
            item["match_type"] = "both"
        elif pid in semantic_ids:
            item["match_type"] = "semantic"
        else:
            item["match_type"] = "keyword"
        results.append(item)

    return {
        "query": request.query,
        "results": results,
        "total_matches": len(results),
        "interpretation": interp.to_dict() if interp else None,
    }
```

- [ ] **Step 4: Rewire the route and delete the dead endpoint**

In `backend/grimoire/api/routes/semantic.py`:

1. Add to `SemanticSearchRequest` (after the `hybrid` field, line 86):

```python
    interpret: bool = Field(True, description="Parse levels/system/type from the query text into lenient filters")
```

2. Replace the body of `semantic_search` (keep the decorator and signature; lines 252–386) with:

```python
    """Search products: interpretation -> candidate union -> chunk re-rank."""
    import json
    import logging
    import traceback
    from grimoire.models import Setting
    from grimoire.services import search_service

    logger = logging.getLogger(__name__)

    try:
        # Read provider from settings (ignore request param)
        result = await db.execute(
            select(Setting).where(Setting.key == "semantic_search_provider")
        )
        setting = result.scalar_one_or_none()
        provider = json.loads(setting.value) if setting else "none"

        if provider == "none":
            raise HTTPException(status_code=400, detail="Semantic search not configured. Set a search provider in Settings.")

        return await search_service.search(db, request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Semantic search failed: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Semantic search error: {e}")
```

Note: `search_service.search` calls `generate_embeddings(..., None, request.model)` with auto-detected provider, matching prior behavior where the settings value gated availability and `generate_embeddings` picked the concrete provider.

3. Delete: `NaturalLanguageQueryRequest` (lines 113–118), `NL_QUERY_PROMPT` (693–709), `interpret_nl_query` (712–787), and the `natural_language_query` endpoint (790–899). Before deleting, run `grep -rn "semantic/query\|interpret_nl_query\|natural_language_query" backend/tests backend/grimoire frontend/src` — the frontend has no hits (verified); if any backend test exercises only this endpoint, delete that test with justification in the commit message.

- [ ] **Step 5: Run tests to verify they pass**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_search_flow.py tests/ -q`
Expected: new tests PASS; no new failures vs baseline.

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/services/search_service.py backend/grimoire/api/routes/semantic.py backend/tests/services/test_search_flow.py
git commit -m "feat(search): two-stage retrieval behind /semantic/search; remove dead /semantic/query"
```

---

### Task 8: Frontend — interpret flag, chips, matched-page snippets

**Files:**
- Modify: `frontend/src/api/semantic.ts`
- Modify: `frontend/src/pages/Library.tsx` (semantic query at lines 87–97, chips row before the few-results hint at line 421, snippet map near `scoreMap` at lines 99–107, `ProductGrid` props at 440–451)
- Modify: `frontend/src/components/ProductGrid.tsx` (pass-through prop)
- Modify: `frontend/src/components/ProductCard.tsx` (snippet line)

**Interfaces:**
- Consumes: Task 7 response shape (`interpretation`, `matched_page`, `snippet`, `match_type`).
- Produces: `semanticSearch(query, topK, filters, options?: { interpret?: boolean })`; `SemanticSearchResponse.interpretation: SearchInterpretation | null`; `snippetMap` prop chain Library → ProductGrid → ProductCard.

- [ ] **Step 1: Update `semantic.ts`**

Replace the search section of `frontend/src/api/semantic.ts`:

```typescript
export interface SearchInterpretation {
  semantic_query: string;
  level_min: number | null;
  level_max: number | null;
  game_system: string | null;
  product_type: string | null;
  source: 'heuristic' | 'llm';
}

export interface SemanticSearchResponse {
  query: string;
  results: any[];
  total_matches: number;
  interpretation: SearchInterpretation | null;
}

export async function semanticSearch(
  query: string,
  topK: number = 20,
  filters: Partial<ProductFilters> = {},
  options: { interpret?: boolean } = {},
): Promise<SemanticSearchResponse> {
  const response = await apiClient.post<SemanticSearchResponse>('/semantic/search', {
    query,
    top_k: topK,
    hybrid: true,
    interpret: options.interpret ?? true,
    game_system: filters.game_system || undefined,
    product_type: filters.product_type || undefined,
    genre: filters.genre || undefined,
    publisher: filters.publisher || undefined,
    author: filters.author || undefined,
    level_min: filters.level_min ? Number(filters.level_min) : undefined,
    level_max: filters.level_max ? Number(filters.level_max) : undefined,
    tags: filters.tags || undefined,
    collection: filters.collection || undefined,
  });
  return response.data;
}
```

(The hardcoded `threshold: 0.3` is deliberately dropped — the backend owns the chunk-score threshold now.)

- [ ] **Step 2: Chips + interpret state in `Library.tsx`**

Add state near the other search state:

```tsx
  // When the user removes an interpretation chip, we re-issue the search with
  // interpret=false plus the remaining interpreted filters made explicit.
  const [interpretDisabled, setInterpretDisabled] = useState(false);
  const [chipFilters, setChipFilters] = useState<Partial<ProductFilters>>({});
```

Reset both in `handleSearch` (before `setActiveSearch(searchInput)`) and in `clearSearch`:

```tsx
    setInterpretDisabled(false);
    setChipFilters({});
```

Update the semantic query (lines 88–97):

```tsx
  const {
    data: semanticData,
    isLoading: semanticLoading,
    error: semanticError,
  } = useQuery({
    queryKey: ['semantic-search', activeSearch, effectiveFilters, chipFilters, interpretDisabled],
    queryFn: () =>
      semanticSearch(activeSearch, 20, { ...effectiveFilters, ...chipFilters }, { interpret: !interpretDisabled }),
    enabled: activeSearch.length > 0 && searchSemantic,
    staleTime: 60000,
  });
```

Add a chip-removal handler and the chips row. Insert the row immediately BEFORE the few-results hint block (line 421):

```tsx
              {searchSemantic && semanticData?.interpretation && !interpretDisabled && (() => {
                const interp = semanticData.interpretation;
                const chips: { key: string; label: string; asFilters: Partial<ProductFilters> }[] = [];
                if (interp.level_min !== null || interp.level_max !== null) {
                  const label = interp.level_min === interp.level_max
                    ? `Level ${interp.level_min}`
                    : `Levels ${interp.level_min ?? '?'}–${interp.level_max ?? '?'}`;
                  chips.push({
                    key: 'level', label,
                    asFilters: {
                      level_min: interp.level_min != null ? String(interp.level_min) : undefined,
                      level_max: interp.level_max != null ? String(interp.level_max) : undefined,
                    },
                  });
                }
                if (interp.game_system) {
                  chips.push({ key: 'system', label: `System: ${interp.game_system}`, asFilters: { game_system: interp.game_system } });
                }
                if (interp.product_type) {
                  chips.push({ key: 'type', label: `Type: ${interp.product_type}`, asFilters: { product_type: interp.product_type } });
                }
                if (chips.length === 0) return null;
                const removeChip = (removedKey: string) => {
                  const remaining = chips.filter((c) => c.key !== removedKey);
                  setChipFilters(Object.assign({}, ...remaining.map((c) => c.asFilters)));
                  setInterpretDisabled(true);
                };
                return (
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                      Interpreted:
                    </span>
                    {chips.map((chip) => (
                      <button
                        key={chip.key}
                        onClick={() => removeChip(chip.key)}
                        className="flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs"
                        style={{
                          backgroundColor: 'var(--color-surface-raised)',
                          color: 'var(--color-text-primary)',
                          border: '1px solid var(--color-border)',
                        }}
                        title="Remove this filter and search again"
                      >
                        {chip.label}
                        <span aria-hidden>×</span>
                      </button>
                    ))}
                  </div>
                );
              })()}
```

- [ ] **Step 3: Snippet map through to cards**

In `Library.tsx`, next to `scoreMap` (line 99):

```tsx
  const snippetMap = useMemo(() => {
    if (!semanticData?.results) return undefined;
    const map: Record<number, string> = {};
    for (const r of semanticData.results) {
      if (r.snippet) {
        map[r.id] = r.matched_page ? `p. ${r.matched_page}: ${r.snippet}` : r.snippet;
      }
    }
    return map;
  }, [semanticData]);
```

Pass it on `<ProductGrid ... snippetMap={searchSemantic ? snippetMap : undefined} />` (line 450 area).

In `ProductGrid.tsx`: add `snippetMap?: Record<number, string>;` to the props interface (line 15 area), destructure it, and pass `snippet={snippetMap?.[product.id]}` to `ProductCard` next to the existing `score={scoreMap?.[product.id]}` (line 102).

In `ProductCard.tsx`: add `snippet?: string;` to the props interface (line 15 area) and destructure. Render it directly below each of the two existing score renderings (list view ~line 123, grid view — put it in the card body under the title if the grid layout has no room for two lines, list view alone is acceptable if the grid card is too tight; at minimum the list view MUST show it):

```tsx
          {snippet && (
            <p
              className="mt-1 text-xs italic line-clamp-2"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {snippet}
            </p>
          )}
```

- [ ] **Step 4: Typecheck**

Run (from `frontend/`): `npx tsc -b`
Expected: only the pre-existing `Settings.tsx` 'Shield' error. Fix any new errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/semantic.ts frontend/src/pages/Library.tsx frontend/src/components/ProductGrid.tsx frontend/src/components/ProductCard.tsx
git commit -m "feat(frontend): interpretation chips + matched-page snippets in semantic search"
```

---

### Task 9: DCC level backfill script

**Files:**
- Create: `backend/scripts/data/dcc_module_levels.csv`
- Create: `backend/scripts/backfill_dcc_levels.py`
- Test: `backend/tests/test_dcc_backfill.py` (create)

**Interfaces:**
- Consumes: `Product.level_range_min/max`, `grimoire.config.settings.database_url`.
- Produces: standalone script `python scripts/backfill_dcc_levels.py [--dry-run]`; pure helpers `parse_module_number(text) -> str | None` and `normalize_title(text) -> str` importable for tests.

- [ ] **Step 1: Build the CSV snapshot**

Use WebFetch on `https://en.wikipedia.org/wiki/List_of_Dungeon_Crawl_Classics_modules` with the prompt: "List every module row across all tables as CSV lines: number,title,level_min,level_max. For a Levels cell like '1-3' output 1,3; for '0' output 0,0; for a single value '5' output 5,5. Skip rows with no level given." Save to `backend/scripts/data/dcc_module_levels.csv` with the header:

```csv
number,title,level_min,level_max
1,Idylls of the Rat King,1,3
27,Revenge of the Rat King,4,6
51,Castle Whiterock,1,15
67,Sailors on the Starless Sea,0,0
100,The Music of the Spheres is Chaos,5,5
```

(The rows above are verified samples; the fetched file replaces/extends them — roughly 200+ rows.) If WebFetch is unavailable in the executing session, commit the CSV with the verified sample rows plus a `# TODO(user): extend from Wikipedia` is NOT acceptable — instead stop and ask the user to paste the table; do not ship a silently-partial dataset.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_dcc_backfill.py`:

```python
"""DCC backfill matching helpers."""
import pytest

from scripts.backfill_dcc_levels import normalize_title, parse_module_number


@pytest.mark.parametrize("text,expected", [
    ("DCC #67 Sailors on the Starless Sea", "67"),
    ("DCC 067 - Sailors on the Starless Sea.pdf", "67"),
    ("dcc-035-gazetteer.pdf", "35"),
    ("DCC RPG Core Rulebook", None),          # no module number
    ("Sailors on the Starless Sea", None),
])
def test_parse_module_number(text, expected):
    assert parse_module_number(text) == expected


def test_normalize_title():
    assert normalize_title("Sailors on the  Starless Sea!") == "sailors on the starless sea"
    assert normalize_title("The Music of the Spheres is Chaos") == \
        normalize_title("the music of the spheres is chaos")
```

Also create `backend/scripts/__init__.py` (empty) if imports fail, or add `backend/` root to path via existing conftest — the tests run from `backend/` so `scripts.backfill_dcc_levels` resolves once `scripts/__init__.py` exists.

- [ ] **Step 3: Run tests to verify they fail**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_dcc_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Write the script**

Create `backend/scripts/backfill_dcc_levels.py`:

```python
"""Backfill level_range_min/max for Dungeon Crawl Classics products from the
checked-in Wikipedia module-list snapshot (scripts/data/dcc_module_levels.csv).

Only writes rows where BOTH level fields are currently NULL. Level 0 is a real
value (funnel adventures). Idempotent. --dry-run prints the match table only.

Usage (from backend/):
    C:/Users/mkemi/miniconda3/python.exe scripts/backfill_dcc_levels.py --dry-run
    C:/Users/mkemi/miniconda3/python.exe scripts/backfill_dcc_levels.py
"""

import argparse
import asyncio
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_MODULE_NUM_RE = re.compile(r"dcc\W{0,3}#?\s*0*(\d+)\b", re.IGNORECASE)


def parse_module_number(text: str) -> str | None:
    """Extract a DCC module number ('DCC #67', 'DCC 067', 'dcc-035') as a
    canonical no-leading-zeros string, or None."""
    m = _MODULE_NUM_RE.search(text or "")
    return m.group(1) if m else None


def normalize_title(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (text or "").lower())).strip()


def load_csv() -> dict:
    """number -> (title, level_min, level_max); also returns title index."""
    path = Path(__file__).parent / "data" / "dcc_module_levels.csv"
    by_number: dict[str, tuple[str, int, int]] = {}
    by_title: dict[str, tuple[str, int, int]] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            entry = (row["title"], int(row["level_min"]), int(row["level_max"]))
            num = str(int(row["number"])) if row["number"].strip().isdigit() else row["number"].strip()
            by_number[num] = entry
            by_title[normalize_title(row["title"])] = entry
    return {"by_number": by_number, "by_title": by_title}


async def run(dry_run: bool) -> None:
    from sqlalchemy import or_, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from grimoire.config import settings
    from grimoire.models import Product

    data = load_csv()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine)

    async with session_factory() as db:
        result = await db.execute(
            select(Product).where(
                Product.level_range_min.is_(None),
                Product.level_range_max.is_(None),
                or_(
                    Product.game_system.ilike("%dungeon crawl%"),
                    Product.game_system.ilike("%dcc%"),
                    Product.title.ilike("%dcc%"),
                    Product.file_name.ilike("%dcc%"),
                ),
            )
        )
        candidates = result.scalars().all()
        print(f"{len(candidates)} DCC-ish products with NULL level range")

        matched, unmatched = [], []
        for p in candidates:
            entry = None
            how = ""
            num = parse_module_number(p.title or "") or parse_module_number(p.file_name or "")
            if num and num in data["by_number"]:
                entry = data["by_number"][num]
                how = f"#{num}"
            else:
                norm = normalize_title(p.title or "")
                if norm and norm in data["by_title"]:
                    entry = data["by_title"][norm]
                    how = "title"
                else:
                    hits = [e for t, e in data["by_title"].items() if t and t in norm] if norm else []
                    if len(hits) == 1:
                        entry, how = hits[0], "title-contains"
                    elif len(hits) > 1:
                        print(f"  AMBIGUOUS (skipped): {p.title!r} matches {len(hits)} modules")
                        continue
            if entry:
                matched.append((p, entry, how))
            else:
                unmatched.append(p)

        for p, (csv_title, lmin, lmax), how in matched:
            print(f"  [{how:>14}] {p.title or p.file_name!r} -> levels {lmin}-{lmax} ({csv_title})")
            if not dry_run:
                p.level_range_min = lmin
                p.level_range_max = lmax

        if unmatched:
            print(f"\n{len(unmatched)} candidates had no match (left untouched):")
            for p in unmatched[:30]:
                print(f"  - {p.title or p.file_name}")

        if dry_run:
            print(f"\nDRY RUN: would update {len(matched)} products")
        else:
            await db.commit()
            print(f"\nUpdated {len(matched)} products")

    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    asyncio.run(run(ap.parse_args().dry_run))
```

- [ ] **Step 5: Run tests, then a dry run against the live DB**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_dcc_backfill.py -v`
Expected: PASS.

Run (from `backend/`): `C:/Users/mkemi/miniconda3/python.exe scripts/backfill_dcc_levels.py --dry-run`
Expected: match table prints; sanity-check a few rows by eye, then run without `--dry-run` ONLY after the user has seen the dry-run output (surface it in the task report).

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/backfill_dcc_levels.py backend/scripts/data/dcc_module_levels.csv backend/scripts/__init__.py backend/tests/test_dcc_backfill.py
git commit -m "feat(data): DCC module level backfill from Wikipedia snapshot (NULL-only, dry-run, idempotent)"
```

---

### Task 10: Golden-query eval harness

**Files:**
- Create: `backend/scripts/search_eval.py`
- Create: `backend/scripts/search_golden.json`

**Interfaces:**
- Consumes: `search_service.search`, `SemanticSearchRequest`, live DB (read-only), Ollama (for query embedding).
- Produces: `python scripts/search_eval.py [--golden PATH] [--save out.json] [--compare baseline.json]` printing per-query hits and overall hit@k + MRR.

- [ ] **Step 1: Create the golden template**

Create `backend/scripts/search_golden.json`:

```json
{
  "_readme": "Fill 'queries' with ~10-20 real searches. 'expect' entries are product IDs (int) or case-insensitive title substrings (str). A query counts as a hit if ANY expected entry appears in the top k results.",
  "queries": [
    {"query": "Undead adventure for 3rd level characters", "expect": ["<fill in a book title you own>"], "k": 10},
    {"query": "dcc funnel adventure", "expect": ["Sailors on the Starless Sea"], "k": 10},
    {"query": "city intrigue campaign", "expect": ["<fill in>"], "k": 10}
  ]
}
```

- [ ] **Step 2: Write the harness**

Create `backend/scripts/search_eval.py`:

```python
"""Golden-query eval for semantic search. Runs against the LIVE DB (read-only)
and requires Ollama up for query embedding.

Usage (from backend/):
    C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py
    C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py --save runs/base.json
    C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py --compare runs/base.json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _is_hit(result: dict, expect) -> bool:
    if isinstance(expect, int):
        return result.get("id") == expect
    title = (result.get("title") or result.get("file_name") or "").lower()
    return str(expect).lower() in title


async def run(golden_path: str, save: str | None, compare: str | None) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from grimoire.config import settings
    from grimoire.api.routes.semantic import SemanticSearchRequest
    from grimoire.services import search_service

    golden = json.loads(Path(golden_path).read_text(encoding="utf-8"))
    queries = [q for q in golden["queries"] if "<fill in" not in json.dumps(q)]
    if not queries:
        print("No usable golden queries — fill in scripts/search_golden.json first.")
        return

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine)

    rows = []
    async with session_factory() as db:
        for entry in queries:
            k = entry.get("k", 10)
            req = SemanticSearchRequest(query=entry["query"], top_k=k, hybrid=True, interpret=True)
            out = await search_service.search(db, req)
            results = out["results"]
            first_rank = None
            for rank, r in enumerate(results, start=1):
                if any(_is_hit(r, e) for e in entry["expect"]):
                    first_rank = rank
                    break
            rows.append({
                "query": entry["query"],
                "hit": first_rank is not None,
                "rank": first_rank,
                "rr": (1.0 / first_rank) if first_rank else 0.0,
                "top": [r.get("title") or r.get("file_name") for r in results[:3]],
            })
    await engine.dispose()

    hits = sum(1 for r in rows if r["hit"])
    mrr = sum(r["rr"] for r in rows) / len(rows)
    for r in rows:
        mark = f"HIT @{r['rank']}" if r["hit"] else "MISS"
        print(f"  [{mark:>7}] {r['query']!r}  top3={r['top']}")
    print(f"\nhit@k: {hits}/{len(rows)} ({hits / len(rows):.0%})   MRR: {mrr:.3f}")

    summary = {"hit_rate": hits / len(rows), "mrr": mrr, "rows": rows}
    if save:
        Path(save).parent.mkdir(parents=True, exist_ok=True)
        Path(save).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"saved -> {save}")
    if compare:
        base = json.loads(Path(compare).read_text(encoding="utf-8"))
        print(f"\nvs {compare}: hit_rate {base['hit_rate']:.0%} -> {summary['hit_rate']:.0%}, "
              f"MRR {base['mrr']:.3f} -> {summary['mrr']:.3f}")
        for b, n in zip(base["rows"], rows):
            if b["hit"] != n["hit"]:
                print(f"  CHANGED: {n['query']!r}: {'MISS->HIT' if n['hit'] else 'HIT->MISS'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="scripts/search_golden.json")
    ap.add_argument("--save", default=None)
    ap.add_argument("--compare", default=None)
    args = ap.parse_args()
    asyncio.run(run(args.golden, args.save, args.compare))
```

- [ ] **Step 3: Smoke-test**

Run (from `backend/`): `C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py`
Expected: with the template's placeholder entries filtered out, either runs the one filled DCC query (needs Ollama up) or prints the "fill in" message. Either outcome is a pass for this task.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/search_eval.py backend/scripts/search_golden.json
git commit -m "feat(eval): golden-query search eval harness (hit@k, MRR, save/compare)"
```

---

### Task 11: Tuning + final verification (user-in-the-loop)

**Files:**
- Modify (as tuning dictates): constants in `backend/grimoire/services/search_service.py`
- Modify: `backend/scripts/search_golden.json` (user fills real queries)

- [ ] **Step 1: User fills the golden set** — CHECKPOINT: ask the user for ~10–20 real queries with expected books; update `search_golden.json`. Blocked on user input.

- [ ] **Step 2: Baseline run** — `C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py --save runs/baseline.json` (needs Ollama up and the app's DB present; note that mid-re-embed coverage affects absolute numbers — record the SV count alongside: `SELECT COUNT(*) FROM product_search_vectors`).

- [ ] **Step 3: Tune** — vary one constant at a time (`CHUNK_SCORE_THRESHOLD` 0.35/0.45/0.55; `KEYWORD_RRF_WEIGHT` 0.5/1.0; `TOP_K_CHUNKS` 1/3/5), re-run with `--compare runs/baseline.json`, keep the best. Commit each accepted change with the numbers in the commit message.

- [ ] **Step 4: Full gates**
  - Backend: `C:/Users/mkemi/miniconda3/python.exe -m pytest` from `backend/` — no new failures vs baseline.
  - Frontend: `npx tsc -b` from `frontend/` — only the pre-existing Settings.tsx error.

- [ ] **Step 5: Manual UI pass** — CHECKPOINT: user starts the app, tries "Undead adventure for 3rd level characters" and a few golden queries in the Library semantic search; verifies chips render and are removable, snippets show matched pages, results feel right.

- [ ] **Step 6: Commit tuning results**

```bash
git add backend/grimoire/services/search_service.py backend/scripts/search_golden.json
git commit -m "tune(search): retrieval constants from golden-query eval"
```

---

## Self-Review

**Spec coverage:**
- Phase 0: page-anchored storage (spec) → Tasks 1–2; page-tagged chunks + 1000/100 + `ProductEmbedding` columns → Task 3; all three embed paths → Task 4; "mass pass waits for Phase 0" → Global Constraints + Task 4 commit message. ✓
- Phase 1: heuristics always / LLM optional+validated+5s+cache → Task 5; lenient-vs-strict filters → Task 7 (`build_interpreted_conditions` + explicit-wins merge); chips + `interpret:false` removal → Task 8. ✓
- Phase 2: SV cache, candidate union w/ pre-filter, chunk re-rank top-3-mean, RRF fuse, threshold on chunk scores, BM25-only survival, FTS-only fallback, response fields, `/semantic/query` deletion → Tasks 6–7. ✓
- Supporting: DCC backfill (NULL-only, level 0, dry-run, ambiguous-skip) → Task 9; eval harness (hit@k, MRR, save/compare, gating tuning) → Tasks 10–11. ✓
- Error handling: LLM failure → heuristic (Task 5); FTS failure → semantic-only (Task 7 try/except); zero SVs → FTS-only (Task 7); legacy JSON → NULL pages (Tasks 2–4); dim filter (Task 6). ✓

**Placeholder scan:** all code steps show full code; the two user-input checkpoints (golden queries, manual UI pass) are explicitly user-blocking, not TBDs; the CSV step mandates stopping rather than shipping partial data. ✓

**Type consistency:** `Interpretation` fields/`to_dict` (Task 5) match `search()` usage and the response's `interpretation` dict (Task 7) and `SearchInterpretation` TS type (Task 8). `build_chunks_for_product(preamble, pages, flat_text, chunk_size, overlap)` identical in Tasks 3/4. `chunk_score`, `sv_top_candidates`, `merge_candidates`, `load_candidate_chunks`, `rerank_by_chunks` signatures match between Task 6 definitions and Task 7 call sites. `page_start`/`page_end` names consistent across model, `_ensure_columns`, embed paths, and `load_candidate_chunks` meta. ✓
