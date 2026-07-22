# Extraction Quality: OCR Routing + Table Reconstruction

**Date:** 2026-07-21
**Status:** Design approved, ready for implementation planning
**Scope:** Backend text-extraction pipeline (`grimoire/processors/text_extractor.py` and callers)

## Origin

Investigation started from a comparison: the online tool
[pdf2md.morethan.io](https://pdf2md.morethan.io) ([jzillmann/pdf-to-markdown](https://github.com/jzillmann/pdf-to-markdown),
MIT) produced visibly cleaner output than Grimoire on the Xcrawl Classics RPG
corebook (`XCC_RPG_Corebook_Digital_v2.pdf`, 394 pages, 235 MB). The user's
symptom: Grimoire "merged columns of text together in a mess"; pdf2md had clean
column separation and clean tables.

Root-cause investigation (see Evidence) found the "cleaner" gap is **mostly not
a better algorithm** — it is that Grimoire OCR'd a document that has a perfectly
good text layer, and OCR destroys column structure. pdf2md never OCRs (it reads
the text layer via pdf.js). A genuine secondary gap is table reconstruction,
where pdf2md's approach is legitimately better and worth borrowing.

## Evidence

**OCR misrouting (primary problem).**
- The corebook's stored extraction (`data/text/17442.json`) has `method:
  "tesseract_ocr"`. Its text interleaves the two columns line-by-line, e.g.
  `"...a player may choose their characters military, police, doctors, firemen,
  actual wizards (not blast occupation, but once again we must stress..."` —
  left-column and right-column lines glued together. That is the "mess."
- `detect_needs_ocr()` samples only the **first 3 pages**. For this book those
  are the cover, inside art, and title page: 33 chars/page average, 5 images →
  `needs_ocr = True` for the entire 394-page book.
- The body pages have a rich text layer. Running `pymupdf4llm` live on pages
  24 / 45 / 60 produces clean column separation, correct reading order (full
  left column, then full right column), proper headings, and dehyphenated prose.
- **Blast radius:** in a 6,000-book sample of `data/text/*.json`, method
  distribution was `pymupdf4llm: 4884`, `tesseract_ocr: 895`, `pymupdf: 221`.
  Of the OCR'd books, **339 are ≥20 pages** — i.e. hundreds of multi-page books
  in the library likely carry the same whole-document column-merge corruption.

**Table shredding (secondary problem).**
- Even on the correct text-layer path, `pymupdf4llm` mangles dense stat tables.
  On page 60, "Table 1-20: The Half-Elf" becomes
  `Ta | ble 1 | -20: The half-el | f`, and data columns are misaligned.
- The underlying block text is clean and row-aligned. `page.get_text("blocks")`
  returns each table row as one block with newline-separated cells
  (`'Acrobatics*\n+1\n+3\n+5\n+7\n+8\n+9\n+10\n+11\n+12\n+13'`).
- Built-in table finders both fail: `find_tables(strategy="lines")` splits the
  table into 8 one-row fragments; `strategy="text"` merges both page tables into
  one wrong 37×16 grid that shreds the spanning title.
- Row-major reconstruction from block grouping is clean, and is actually more
  correct than pdf2md here (pdf2md rendered `Acrobatics* +3 +5 +7…`; the true
  row is `+1 +3 +5 +7…`, which block-grouping recovers correctly).

**Integration constraint.**
- `pymupdf4llm.to_markdown` (pinned 1.28.0) is declared `(*args, **kwargs)` and
  **silently ignores `table_strategy`** — output is byte-identical for `None`,
  `"lines_strict"`, and `"text"`. Therefore pymupdf4llm's table detector cannot
  be disabled via a parameter; tables must be handled by substitution/post-
  processing of its output.

## Non-goals

- Character-encoding cleanup. `pymupdf`/MuPDF emits `U+FFFD` (`�`) for this
  book's curly quotes, apostrophes, and degree sign `°` (`"athlete�s"`, `"60�"`)
  because the font's ToUnicode mapping is incomplete; pdf.js decodes them. This
  is a real but separate, pervasive, cosmetic gap. Deferred.
- Per-page hybrid OCR (text-layer pages via pymupdf4llm, image-only pages via
  OCR, stitched by page number). Deferred; see Component 1 limitation.
- Replacing the extractor with a pdf.js / Node-based path. Rejected: adds a
  runtime dependency and the two components below recover the bulk of the gap.

## Design

### Component 1 — Text-layer coverage router

Replace first-3-pages sampling with a whole-document coverage scan.

- New `assess_text_layer(pdf_path) -> dict`: iterate every page, read
  `len(page.get_text().strip())` (text-layer read only — no rendering). Return:
  - `total_pages`
  - `pages_with_text` — count of pages with `>= MIN_CHARS` (default 100)
  - `coverage` — `pages_with_text / total_pages`
  - `needs_ocr` — `True` only when `coverage < COVERAGE_THRESHOLD`
    (default 0.10), i.e. the document is image-only throughout
  - `reason` — human-readable explanation
- Wire into `extract_text_with_ocr_fallback()` in place of the `detect_needs_ocr`
  sampling decision. Preserve `force_ocr`. The old email/transaction watermark
  filtering in `detect_needs_ocr` is subsumed by whole-doc coverage (a single
  watermark page cannot swing the verdict), so `detect_needs_ocr` can be
  retired or reduced to a thin wrapper over `assess_text_layer` for callers/tests
  that still reference it.
- Verdict on the corebook: body pages ~2000+ chars, front matter ~33 chars →
  coverage ≈ 0.98 → text-layer path. A true scan → coverage ≈ 0 → OCR path.

**Known limitation (accepted):** a mostly-digital book with a few genuinely
scanned insert pages routes fully to the text-layer path; those insert pages
lose their text. This is the tradeoff for the whole-doc decision the user chose.
Per-page hybrid routing is the deferred upgrade.

### Component 2 — Row-major table reconstruction

New module `grimoire/processors/table_reconstructor.py`.

- `reconstruct_tables(page) -> list[TableRegion]` where each region carries a
  bounding box (for ordering) and clean markdown. Method:
  1. **Primary — block-row grouping.** Take `page.get_text("blocks")`; identify
     table-row blocks (text splits into `>= 3` short cells; runs of consecutive
     vertically-adjacent such blocks form a table). Emit each row as a markdown
     pipe row, row-major. Header rows sit on top; no attempt to parse spanning
     titles into the grid (that is exactly what shreds them).
  2. **Fallback — gap-based column clustering** (pdf2md's core idea, ported):
     for pages where blocks do not split cleanly, take `page.get_text("words")`,
     cluster into rows by y-overlap and into columns by x-gap analysis, then emit
     the grid. This mirrors pdf-to-markdown's `CompactLines` + column logic.
- **Integration — substitution.** Because pymupdf4llm's table detector cannot be
  disabled (see constraint), per page:
  1. Run pymupdf4llm as today (per-page via `page_chunks`).
  2. Locate its table output — contiguous runs of lines beginning with `|`.
  3. Strip those runs and insert the reconstructed clean tables at the same
     positions. Pair multiple tables per page by vertical (y) order.
  4. Prose, headings, bold/italic, and dehyphenation from pymupdf4llm are
     preserved everywhere outside the stripped table runs.

### Component 3 — Re-extraction migration

The routing fix only helps already-ingested books if they are re-extracted.

- One-time repair pass (endpoint or script, following the existing repair-
  endpoint pattern): enumerate products whose stored extraction `method` is
  `tesseract_ocr` (read from each `extracted_text_path` JSON), run
  `assess_text_layer` on the source PDF, and re-queue those that now read as
  text-layer. True image-only scans are left as OCR.
- Must be resumable and must respect the processing queue and the "I'm working"
  pause. Re-queued books flow through the normal downstream re-embed pipeline.
- Interaction note: this branch (`feat/search-accuracy`) has search/embedding
  work and a mass re-embed in flight. Re-extracting hundreds of books will
  produce a large re-embed load; sequence accordingly.

## Testing

- **Routing:** synthetic `fitz` PDFs — all-text, all-image, and the corebook
  shape (art-heavy front matter + text body) — asserting `assess_text_layer`
  verdicts. Threshold constants covered at their boundaries.
- **Tables:** golden test on a constructed table fixture asserting clean
  row-major output (`Acrobatics* | +1 | +3 | +5 | …`) and absence of a shredded
  title cell.
- **Migration:** unit test that a `tesseract_ocr` product whose PDF has a text
  layer is selected for re-queue, and an image-only one is not.
- Re-measure test baselines before/after per the testing memory (do not quote
  baselines from docs). Manual e2e verification on the real corebook: confirm it
  re-extracts via the text-layer path with clean columns and readable tables.

## References

- pdf-to-markdown pipeline stages of interest (MIT):
  `CalculateGlobalStats` (global height/font/spacing histograms),
  `DetectHeaders` (heights above body baseline → H2/H3/…),
  `RemoveRepetitiveElements` (hash first/last line ignoring digits/space; drop
  items recurring on > 2/3 of pages), `CompactLines` + `VerticalToHorizontal`
  (line/column reconstruction). Only the column/table reconstruction idea is
  borrowed here; `RemoveRepetitiveElements` (watermark/footer stripping) is a
  natural future add-on but out of this scope.
