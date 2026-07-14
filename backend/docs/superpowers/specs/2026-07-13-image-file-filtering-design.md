# Image-File Filtering Design

**Date:** 2026-07-13
**Status:** Design approved, ready for implementation plan
**Scope:** Keep map / tile / stock-art PDFs out of text & OCR processing — both by fixing detection for future scans and by reclassifying the existing backlog.

## Problem

Map and image-only PDFs (battlemaps, tiles, stock art) have no meaningful text
layer. When they reach the text-extraction pipeline they either extract nothing
or, worse, get routed to OCR — the slowest queue path — only to be flagged
`text_unextractable` after wasting CPU. They also pollute search with empty or
garbage vectors.

Grimoire already has a two-tier image classifier
(`processors/image_classifier.py`): filename/path is the primary signal, and a
10-page content sample confirms before diverting. But it is missing large
categories of real map files:

- **Word-boundary bug.** Map patterns are `\bmap\b` / `\bmaps\b`. The publisher
  Heroic Maps ships files named `HeroicMaps_*.pdf` — `cMaps` has no word
  boundary, so the regex never fires. ~285 pending `HeroicMaps_` files slip
  through as `text` tasks.
- **Missing keywords.** `tile` / `tiles`, `geomorph`, `battlemap`, and grid
  markers (`GRID` / `NoGRID`) are not classification keywords, so `Village_tiles`
  and similar miss.
- **No publisher awareness.** Entire publisher folders are 100% maps
  (Heroic Maps, Map Alchemists, Black Scrolls Games, 0one Games,
  Animated Dungeon Maps). Nothing recognizes them.

### Measured impact (2026-07-13)

Pending `text`/`ocr_text` items under the five known map-publisher folders:

| Publisher folder      | products | pending text/OCR |
|-----------------------|----------|------------------|
| Heroic Maps           | 298      | 285              |
| Map Alchemists        | 48       | 19               |
| Black Scrolls Games   | 24       | 16               |
| 0one Games            | 8        | 3                |
| Animated Dungeon Maps | 0        | 0 (not yet scanned) |
| **Total**             |          | **323**          |

~10% of the pending queue, cleared immediately, plus prevention for future
scans and publishers added later.

## Design

### 1. `_normalize_for_matching(text)`

New helper in `image_classifier.py`. Before any pattern/blacklist matching:

- insert a space at camelCase transitions (`HeroicMaps` → `Heroic Maps`)
- treat `_` and `-` as spaces

This fixes the word-boundary class of bugs generally, and lets a single
blacklist entry (`heroic maps`) match both the `Heroic Maps` folder in the path
and the `HeroicMaps` token in the filename. Applied to the combined
`"{filename} {file_path}"` search string that classification already uses.

### 2. Publisher/marker blacklist — `_IMAGE_CONTENT_PUBLISHERS`

A list of case-insensitive substrings matched against the *normalized*
path+filename. Seeded with:

- `heroic maps`
- `map alchemists`
- `black scrolls games`
- `0one games`
- `animated dungeon maps`

User-appendable as more all-map publishers are found.

**A blacklist hit is decisive: classify as `Map`, set `is_image_content=True`,
divert to `extract_images`, and skip content analysis entirely** (no file open).
This is the fast path — the backlog reclassification of blacklisted publishers
requires zero PDF I/O. Accepted tradeoff: a non-map file placed under a
blacklisted publisher folder would be diverted; if this ever bites, we revisit
(e.g. re-add a confirmation step for specific entries). Not solved now.

### 3. Keyword fixes (still content-confirmed)

Extend `_CLASSIFICATION_RULES` Map patterns with `tile(s)`, `geomorph`,
`battlemap`, and grid markers (`\bgrid\b`, `nogrid`). These — plus the
now-working `\bmap\b` via normalization — continue through the **existing
two-tier confirmation**: a 10-page sample must show ≥50% image-dominant pages
before diverting. This keeps false positives out: a real book that merely
mentions "map" in its name is not skipped.

Order of evaluation in `detect_image_content`:
1. Blacklist hit → divert immediately (no content analysis).
2. Otherwise existing flow: name keyword + content confirmation, or
   overwhelming-image-content fallback for no-signal files.

### 4. Action on a detected map — unchanged

Once `is_image_content=True`, the existing `handle_text_task` branch already:
flags the product, queues `extract_images`, auto-tags **Map**, and skips
text/OCR. No change needed — this design only makes detection *reach* that
branch for more files.

### 5. Backlog reclassification

A one-shot pass over pending `text` / `ocr_text` queue items that runs the
improved classifier and, for confirmed maps:

- cancels the pending `text`/`ocr_text` queue row,
- sets `is_image_content=True` (+ `product_type`/Map tag),
- queues an `extract_images` task.

Blacklist hits divert with no file open (fast); keyword hits open the file for
the 10-page confirmation. Reuses the existing reclassification machinery
(`2026-03-14-product-reclassification-design.md`, `test_bulk_reclassify`,
`reclassify_failures`) rather than adding a parallel path. Exposed the same way
existing reclassify actions are (endpoint / button), consistent with current
UX.

## Out of scope

- **Zip-archive scanning.** ~3,139 archives under `D:\Drivethrurpg` are not
  scanned at all (`scanner.py` uses `rglob("*.pdf")` and never opens `.zip`).
  Many contain maps/tiles/stock art. This is a separate, larger feature with its
  own design (extract-in-place vs read-from-zip, non-PDF contents, multi-format
  dedup, idempotent re-scan) and will get its own spec. The blacklist/classifier
  here will apply to archive contents once they are scanned.
- Reworking the confirmation thresholds for keyword hits.
- Any change to how extracted map images are displayed.

## Testing

Unit tests in the existing `image_classifier` / reclassify test modules:

- `_normalize_for_matching`: `HeroicMaps` → matches map; `Village_tiles` →
  matches tile; `Forest_river` → no match (no signal).
- Blacklist hit diverts **without opening the file** (assert content analysis
  not called / no PDF read).
- Blacklisted publisher path (`D:\...\Heroic Maps\...`) → `is_image_content`,
  classification `Map`.
- Keyword-but-text-heavy file (name matches `map`, content mostly text) → **not**
  diverted (false-positive guard).
- No-signal file (`Forest_river.pdf`) with normal text → untouched.
- Backlog reclassify: a blacklisted pending `ocr_text`/`text` item is moved off
  the text queue and an `extract_images` task is queued.

## Key decisions (from brainstorming)

- Scope: **both** — fix detection for future scans *and* reclassify the ~323
  backlog items.
- Detection confidence: keyword hits stay **content-confirmed**; **blacklist
  hits skip confirmation** (user decision — accept small false-positive risk,
  address later if needed).
- Action on match: **divert to image extraction + tag Map** (existing behavior),
  not a bare skip — the user keeps a searchable gallery entry with extracted
  images.
- Publisher blacklist matches on the **normalized path**, catching both folder
  and filename forms with one entry.
