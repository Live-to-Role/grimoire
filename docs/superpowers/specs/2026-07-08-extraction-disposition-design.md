# Extraction Disposition — Stop Re-Running Unextractable PDFs

**Date:** 2026-07-08
**Status:** Design approved, pending spec review

## Problem

PDFs that are image collections (stock art / maps) or that simply have no
extractable text get **re-queued and re-processed forever**, and pile up as
"failed" queue items (~5,093 at time of writing).

Root cause, traced in the code:

- `handle_text_task` already detects image content (`detect_image_content`),
  sets `product.is_image_content = True`, sets `product_type`, auto-tags, and
  queues image extraction — **but nothing excludes these products from future
  text-extraction runs.** Every `POST /queue/text-extraction/queue-all` and every
  scan filters on `text_extracted == False`, so image-only products (which never
  get `text_extracted = True`) are re-queued each time.
- There is **no terminal "this PDF has no extractable text" state.** Genuinely
  unextractable PDFs (encrypted, corrupt, OCR yields nothing) fail, stay
  `text_extracted == False`, and get re-queued indefinitely.
- `ai_identify` tasks depend on extracted text but are not gated on it, so they
  are queued and fail for products that can never be identified.

The distinction that must be preserved: **permanent, per-product** failures
(image-only, no text, corrupt) should be flagged and skipped; **transient /
environmental** failures (Ollama down, Tesseract missing, I/O error) must stay
retryable — we never flag a product just because a provider was misconfigured.

## Goals

- Auto-flag image-only and genuinely-unextractable PDFs so they are excluded
  from all text-extraction and AI-identify re-queue paths.
- Keep transient/environmental failures retryable.
- One-time reclassification + cleanup of the existing failed backlog.
- A UI surface to see what was flagged and to override (retry) after extraction
  improves.

## Non-Goals

- Embed 400 hardening (sub-batching chunks) — a separate minor follow-up (~3 items).
- Changing the detection heuristics themselves (`detect_image_content`,
  `detect_needs_ocr`) — reused as-is.
- A per-(product, task) disposition table — rejected as over-engineered; two axes
  (text, ai_identify) are covered by product-level flags.

## Data Model

Add two columns to `Product`, registered in `database.py::_ensure_columns()`
(the existing add-column-for-older-DBs mechanism):

| Column | Type | Meaning |
|---|---|---|
| `text_unextractable` | `BOOLEAN DEFAULT 0` | Tried and cannot obtain usable text (encrypted/corrupt/OCR-empty). |
| `extraction_error` | `TEXT` (nullable) | Short human-readable reason, shown in the UI. |

`is_image_content` (already exists, already auto-set) is the "image-only"
terminal state. AI-identify eligibility is **derived** from these flags, not
stored.

**Terminal (skip) predicate:** `is_image_content OR text_unextractable`.

## Detailed Design

### 1. Classify failures in the handlers

In `handle_text_task` and `handle_ocr_text_task` (`queue_processor.py`):

- **Image content** → unchanged (`is_image_content = True`); gating (below) now
  excludes it. Returns success as today.
- **Permanent no-text** → set `product.text_unextractable = True`,
  `product.extraction_error = <reason>`, commit, then `raise TaskError(reason)`.
  The existing failure path treats `TaskError` as permanent (no retry), so this
  reuses established semantics. Permanent conditions:
  - PDF encrypted or corrupt (PyMuPDF/`fitz` raises on open/read).
  - OCR completed but produced empty / whitespace / below a small char threshold
    (`MIN_EXTRACTED_CHARS`, e.g. 20) of text.
  - Non-image PDF with no text layer and OCR produced nothing.
- **Transient** → do **not** set the flag; return `False` (retry via
  `max_attempts`) or raise a non-`TaskError` exception. Transient conditions:
  Tesseract/pdf2image unavailable, file temporarily missing, I/O error, any
  unexpected exception.

`extraction_error` reason strings are short and stable (e.g. `"encrypted"`,
`"corrupt pdf"`, `"no text after ocr"`, `"no text layer"`).

### 2. Gate every re-queue entry point

Add `AND NOT is_image_content AND NOT text_unextractable` to the product
selection in:

- `routes/queue.py::queue_all_for_text_extraction` — **both** the `force=True`
  and the default branch. (Consequence: the existing "Re-extract All (force)"
  button will now skip known image-only / unextractable PDFs. The explicit
  override is the "Retry unextractable" action in §4.)
- `services/scanner.py` — the scan-time `task_type="text"` auto-queue (~L254).
- `queue_processor.py::queue_ai_identify_if_enabled` and any ai_identify
  auto-queue — additionally require `text_extracted == True` (no text ⇒ cannot
  identify).
- `queue_processor.py::_auto_requeue_embeddings` — add `AND NOT
  text_unextractable` (belt-and-suspenders; these have no text anyway).

### 3. One-time reclassify + cleanup

New idempotent endpoint `POST /queue/reclassify-failures` (also surfaced as a UI
button). It walks failed `text` / `ocr_text` / `ai_identify` queue items and
their products and, per item:

- Product is `is_image_content`, or the failure indicates a **permanent no-text**
  condition (error text matches known permanent patterns, or the product has no
  text and no text layer) → ensure `text_unextractable`/reason is set and
  **delete** the failed item.
- `ai_identify` failure on a product with no extracted text → **delete** (it will
  re-queue once text exists).
- Failure looks **transient/environmental** (error text matches provider /
  tooling / I/O patterns) → **leave** the item as-is (retryable).

Returns counts: `{ flagged, cleared, left_retryable }`. Safe to run repeatedly.

Classification uses the queue item's `error_message` plus product flags. The
permanent/transient matching lives in one small pure helper
(`classify_extraction_failure(error_message, product) -> "permanent" | "transient"`)
so it is unit-testable and shared by §1's decision where practical.

### 4. UI: review + override (Processing tab, `LibraryManagement.tsx`)

- A summary line in the Text Extraction section:
  "N image collections · M unextractable — excluded from extraction."
  Counts come from extending the existing library stats endpoint's `processing`
  block with `image_content` and `unextractable` counts.
- **"Retry unextractable"** button — clears `text_unextractable` (+ reason) for
  all flagged products and re-queues them for text extraction. The explicit
  escape hatch for when extraction quality improves. (New endpoint, e.g.
  `POST /queue/text-extraction/retry-unextractable`.)
- **"Reclassify failed queue"** button — wired to §3.
- The existing "dismiss & mark as art" flow stays.

### 5. Migration

Two rows added to `_ensure_columns()`:
`("products", "text_unextractable", "BOOLEAN DEFAULT 0")` and
`("products", "extraction_error", "TEXT")`. Add the mapped columns to
`models/product.py`. No destructive migration; existing DBs get the columns on
next `init_db()`.

## Testing

Backend (pytest):
- Gating: `queue_all_for_text_extraction` (default + force), the scan text-queue,
  ai_identify queueing, and `_auto_requeue_embeddings` all exclude products with
  `is_image_content` or `text_unextractable`.
- Handler classification: a permanent no-text condition sets `text_unextractable`
  + `extraction_error` and raises `TaskError` (no retry); a transient condition
  (e.g. Tesseract missing) does **not** set the flag and stays retryable.
- `classify_extraction_failure` pure-function unit tests over representative
  error strings (encrypted, corrupt, no-text vs. provider/tooling/IO).
- Reclassify pass: image-only/no-text failures get flagged + cleared, transient
  left retryable, and a second run is a no-op (idempotent).

Frontend: `npx tsc -b` gate (no test harness); manual verification of the two
buttons and the summary counts.

## Files Touched (anticipated)

- `backend/grimoire/models/product.py` — two new mapped columns.
- `backend/grimoire/database.py` — two `_ensure_columns` rows.
- `backend/grimoire/services/queue_processor.py` — handler classification;
  ai_identify + embed-requeue gating; `classify_extraction_failure` helper.
- `backend/grimoire/services/scanner.py` — gate the scan text auto-queue.
- `backend/grimoire/api/routes/queue.py` — gate `queue-all` (default + force);
  add `reclassify-failures` and `retry-unextractable` endpoints.
- `backend/grimoire/api/routes/` (library stats) — expose flagged counts.
- `frontend/src/pages/LibraryManagement.tsx` — summary + two buttons.
- Tests under `backend/tests/`.

## Out of Scope / Follow-ups

- Embed 400 hardening (sub-batch chunks; flag embed-skip after persistent 400).
- Smarter detection heuristics.
