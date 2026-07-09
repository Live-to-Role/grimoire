# Oversized-PDF Guard + Smallest-First Processing

**Date:** 2026-07-08
**Status:** Design approved, pending spec review

## Problem

A single pathological PDF can stall the entire extraction queue. Observed live: a
**760 MB, 802-page** scanned document (product 13281) was picked up by the worker
and triggered full per-page OCR / image analysis. Worker log after it started:

```
Product 13281 ... (item 8, task_type=text) started 18:50:52
Image too small to scale!! (2x36 vs min width of 3)
Line cannot be recognized!!
... (repeating Tesseract/leptonica OCR output)
```

It ran ~26+ minutes with **zero throughput** and no completion. Because the worker
processes **sequentially**, this one file blocked all ~18,270 other pending items.
It was not crashed — it was legitimately grinding on 802 pages of OCR (potentially
an hour-plus).

Two compounding causes:
1. **No size/page guard** — the extraction handler attempts detection + layout
   extraction + OCR on any PDF regardless of size, and a huge scanned file drives
   this into a multi-hour grind (and heavy memory use during layout parsing).
2. **Largest-first ordering** — the force re-extract queued products by
   `file_size` descending, and the worker's tiebreaker (`get_next_pending_item`)
   also prefers largest. So the biggest, slowest files run *first* and
   head-of-line-block the fast majority.

## Goals

- **Skip** PDFs above a size/page threshold at worker pickup, flagging them so
  they are excluded from re-queue and visible for override — before any expensive
  detection/OCR starts.
- Process the queue **smallest-first** so the fast majority drains quickly and
  giants go last.

## Non-Goals

- Queue-time filtering (the handler guard catches the already-queued backlog; no
  need to also filter at enqueue).
- A Settings-configurable threshold UI (named constants only for now).
- Size-guarding `embed` / `ai_identify` tasks — they do not run the heavy layout
  parse/OCR.
- A distinct "oversized" disposition column — reuse the existing
  `text_unextractable` flag (shipped in the extraction-disposition feature).

## Design

### 1. Thresholds (named constants in `queue_processor.py`)

```python
MAX_EXTRACTION_FILE_MB = 250
MAX_EXTRACTION_PAGES = 1000
```

Size is the primary guard (it tracks the memory/OCR cost and is always known
without opening the file). Pages is a secondary net.

### 2. Skip guard

A pure helper:

```python
def _oversized_skip_reason(product) -> str | None:
    size_mb = (product.file_size or 0) / (1024 * 1024)
    if size_mb > MAX_EXTRACTION_FILE_MB:
        return f"oversized: {size_mb:.0f} MB (limit {MAX_EXTRACTION_FILE_MB} MB)"
    if product.page_count and product.page_count > MAX_EXTRACTION_PAGES:
        return f"oversized: {product.page_count} pages (limit {MAX_EXTRACTION_PAGES})"
    return None
```

Called as the **first step** of both `handle_text_task` and
`handle_ocr_text_task` — before any file open, detection, or extraction. On a
hit:

```python
product.text_unextractable = True
product.extraction_error = reason
await db.commit()
raise TaskError(f"Product {product.id} '{product.file_name}': {reason}")
```

This reuses the extraction-disposition plumbing: `TaskError` is a permanent
failure (no retry), the flag excludes the product from every re-queue path
(queue-all default+force, scanner, ai_identify, embed re-queue), it appears in the
library-stats `unextractable` count, and the existing **"Retry unextractable"**
button is the explicit override to force it through anyway.

**Page-count nuance:** the size check never opens the file. The page check uses
`product.page_count` **only when already populated** (it is set during cover
extraction). If `page_count` is `None`, we do not open the PDF just to count
pages — the size guard alone catches real monsters (e.g. the 760 MB file: caught
by size; its 802 pages are under the 1000 cap anyway).

`handle_ocr_text_task` already has an `except TaskError: raise` clause (from the
disposition work), so the raised `TaskError` propagates rather than being
swallowed by its broad `except Exception`.

### 3. Smallest-first ordering

`get_pending_batch` (the worker's drain query) currently selects
`ProcessingQueue` ordered by `priority desc, created_at asc`, with no size term.
Add a join to `Product` and order:

```
priority desc, Product.file_size asc, created_at asc
```

Covers stay prioritized (priority 8), then smallest files first, then FIFO within
a size. Also flip the existing `Product.file_size.desc()` tiebreaker in
`get_next_pending_item` to `.asc()` for consistency.

## Interaction with current state

The 760 MB item currently stuck (worker Ctrl+C'd) will, on the next worker start,
be reset from `processing` → `pending` by the existing stuck-item recovery. When
the worker next reaches it, the guard fires (760 MB > 250 MB), flags it
`text_unextractable = "oversized: 760 MB (limit 250 MB)"`, and moves on — and with
smallest-first ordering it is reached last anyway.

## Testing

- `_oversized_skip_reason`: unit tests — size over limit → reason; pages over
  limit (with `page_count` set) → reason; both under / `None` inputs → `None`.
- Handler: a product with `file_size` over the limit → `handle_text_task` sets
  `text_unextractable=True` + an "oversized" `extraction_error` and raises
  `TaskError`. The guard runs before file access, so no real PDF file is needed.
- Ordering: `get_pending_batch` over products with mixed `file_size` returns
  items smallest-file first (respecting priority).

## Files Touched (anticipated)

- `backend/grimoire/services/queue_processor.py` — constants,
  `_oversized_skip_reason`, guard at the top of `handle_text_task` /
  `handle_ocr_text_task`, smallest-first ordering in `get_pending_batch` and
  `get_next_pending_item`.
- Tests under `backend/tests/`.

## Out of Scope / Follow-ups

- Settings-configurable thresholds (currently constants).
- Auto-preferring the smaller of near-duplicate files (e.g. the 159 MB
  "Mobile_Friendly" vs the 760 MB print master of the same title).
- Embed 400 hardening; the pre-existing transient-`ai_identify`-`TaskError` bug.
