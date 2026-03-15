# Revision Handling Design

## Problem

Grimoire treats each PDF as an independent product keyed by file path. When a publisher releases a revised version of a product (e.g., `A_Conspiracy_of_Ravens-PDF_(Revised).pdf` alongside `A_Conspiracy_of_Ravens-PDF.pdf`), both appear as separate products. When metadata syncs to Codex, this creates unwanted duplication.

## Goals

- Detect when two products are revisions of the same underlying work
- Supersede the older version: transfer metadata, hide it from the library and Codex sync
- Surface candidates for user confirmation before taking action
- Integrate into the existing duplicates view and workflow

## Approach: Extend the Duplicate System

Layer revision detection onto the existing duplicate infrastructure. Revision candidates use `duplicate_reason="revision"` and appear in the duplicates view under a "Revisions" filter. On confirmation, the old product is superseded — metadata transfers to the newer version and the old one is hidden.

## Design

### 1. Revision Detection Engine

**Stem normalization** strips format tags and revision indicators from filenames to produce a canonical stem for comparison:

```
A_Conspiracy_of_Ravens-PDF_(Revised).pdf  →  a_conspiracy_of_ravens
A_Conspiracy_of_Ravens-PDF.pdf            →  a_conspiracy_of_ravens
A_Conspiracy_of_Ravens.pdf                →  a_conspiracy_of_ravens
```

Normalization steps:

1. Remove file extension
2. Strip **trailing** format tags (case-insensitive): `-PDF`, `_PDF`. Only matched at the end of the stem to avoid false positives (e.g., `The_PDF_Guide_to_Dragons` should NOT have `_PDF` stripped).
3. Strip **trailing** revision patterns (case-insensitive): `(Revised)`, `_Revised`, `_v2`, `_2nd_Edition`, `_Updated`, `_Errata`, `_Final`, `(Print_Friendly)`, version numbers like `_v1.2`, etc. Patterns are only matched at the end of the stem to avoid false positives (e.g., `The_Final_Dungeon` should NOT have `_Final` stripped).
4. Lowercase, collapse separators (`-`, `_`, spaces) to `_`, strip trailing separators

The pattern list is a config constant for easy extension without code changes.

**Matching logic:** Compute a product's normalized stem and query for other products with the same stem but different `file_hash`. Matches are revision candidates.

**Determining which is newer:** The primary signal is whether the filename contains a revision indicator (e.g., `_Revised`, `_v2`). A file with a revision indicator is presumed to be the newer version. When neither or both filenames have indicators, fall back to `file_modified_at`, then `created_at`. This avoids relying on filesystem mtime, which can be reset by file copies, zip extraction, or sync tools.

**Groups of 3+:** When more than two products share a normalized stem, all non-newest products point to the single newest one. The "newest" determination uses the same indicator → mtime → created_at precedence.

### 2. Data Model Changes

No new tables. Extend the existing Product model:

- **`normalized_stem`** (String, indexed) — Precomputed normalized filename stem, populated during scan. Enables revision matching via simple DB query.
- **`is_superseded`** (Boolean, default False, indexed) — Set to `True` when a revision is confirmed. Unlike `is_missing`, this is not cleared by the scanner when the file is found on disk, so the superseded state persists across scans.
- **`superseded_by_id`** (FK to Product.id, nullable) — Points to the newer product that supersedes this one. Since the Product model already has one self-referential FK (`duplicate_of_id`), the `superseded_by` relationship must declare `foreign_keys=[Product.superseded_by_id]` explicitly to avoid SQLAlchemy configuration errors.
- **`duplicate_reason`** gains a new valid value: `"revision"` alongside existing `"exact_hash"` and `"same_content"`.

**Why not reuse `is_missing`?** The scanner clears `is_missing` when it re-encounters a file on disk. Since superseded products still exist on disk, every scan would silently undo the supersede. A dedicated `is_superseded` column avoids this.

**Revision candidate flow:**

- Candidate detected → `is_duplicate=True`, `duplicate_of_id=newer_product_id`, `duplicate_reason="revision"` (NOT yet `is_superseded`)
- User confirms → metadata transfers, old product gets `is_superseded=True`, `superseded_by_id=newer_product_id`
- User dismisses → `is_duplicate=False`, `duplicate_of_id=None`, `duplicate_reason=None`

**Note on `duplicate_of_id` direction:** The existing duplicate system points the duplicate at the canonical (older) product. For revisions, `duplicate_of_id` points at the newer product — the semantics are "I was superseded by this product" rather than "I am a copy of this product." This is intentional: the newer product is the one to keep. Revision groups are queried by `normalized_stem`, not by `get_duplicate_groups()` which uses `file_hash`. Revision-specific query functions are needed.

### 3. Metadata Transfer & Supersede Flow

When a revision candidate is confirmed:

1. **Selective metadata transfer** — For each scalar field on the old product, copy to the new product only if the new product's field is `None`/empty. Fields: `title`, `author`, `publisher`, `publication_year`, `description`, `game_system`, `genre`, `product_type`, `setting`, `series`, `series_order`, `level_range_min/max`, `party_size_min/max`, `estimated_runtime`, `format`, `isbn`, `msrp`, `dtrpg_url`, `itch_url`, `themes`, `content_warnings`.

2. **Relationship transfer** — Move tags and collection memberships from old to new product, skipping any that would create duplicates.

3. **Run tracking transfer** — Copy scalar run fields (`run_status`, `run_rating`, `run_difficulty`, `run_completed_at`) to the new product if it has no run data. Reassign `RunNote` records via a bulk `UPDATE` statement (not ORM attribute assignment) to avoid triggering the `cascade="all, delete-orphan"` on the Product.run_notes relationship, which would delete the notes as orphans.

4. **Supersede the old product** — Set `is_superseded=True`, `superseded_by_id=newer_product_id`.

5. **Queue processing** — If the new product hasn't had cover extraction or AI identification yet, queue those tasks.

**Note:** `DeletedDuplicate` tracking is NOT needed here. The superseded product's DB record remains in the database with `is_superseded=True`, so the scanner will find it by `file_path` and skip re-import normally. `DeletedDuplicate` is only for files whose DB records have been fully removed.

### 3a. Orphan Cleanup

If the newer product (pointed to by `superseded_by_id`) is deleted, clear `is_superseded` and `superseded_by_id` on all products that reference it — analogous to `cleanup_orphaned_duplicates()` in the existing duplicate service.

### 4. Scanner Integration & On-Demand Scan

**During regular scan:**

After new product creation and existing duplicate detection, run a revision detection pass:

1. Query products with matching `normalized_stem` but different `file_hash`
2. Filter out products already marked as duplicates, superseded, or missing
3. Mark candidates: `is_duplicate=True`, `duplicate_of_id=newer_product_id`, `duplicate_reason="revision"`
4. Include count in scan results: "Found 3 revision candidates"

**On-demand scan:**

Extend the duplicate scan endpoint with a `scan_type` parameter:

- `"hash"` — existing hash-based detection
- `"revision"` — stem-matching only
- `"all"` — both hash and revision detection

**Backfill:** `_ensure_columns()` adds the `normalized_stem` column with a NULL default. A separate one-time backfill pass then queries all products with NULL `normalized_stem` and computes the value using the Python normalization function. This runs on startup after `_ensure_columns()` and is a no-op once all products have stems populated.

### 5. Duplicates View Integration

**Revisions tab/filter** in the duplicates view, filtering to `duplicate_reason="revision"`. Each group shows:

- Products with the same normalized stem
- Which is identified as newer (by revision indicator presence, then `file_modified_at`)
- Actions: **Confirm** (triggers metadata transfer + supersede) or **Dismiss** (clears duplicate marking)

Revision groups are queried by `normalized_stem` rather than `file_hash`, so they require their own query function separate from existing hash-based `get_duplicate_groups()`.

**Duplicate stats** endpoint gains a revision candidate count alongside existing duplicate count, enabling UI to show "5 duplicates, 3 revision candidates."

### 6. Codex Sync

Add explicit visibility filtering to the contribution service. The contribution/sync pipeline does not currently check product visibility state at all (no `is_missing`, `is_duplicate`, or `is_superseded` filtering). All three should be added. Specifically, superseded products must be excluded from:

- Contribution queue creation (don't queue superseded products for Codex submission)
- Pending contribution processing (skip entries whose product has since been superseded)

### 7. Visibility Filtering

All queries that return "visible" products must filter `is_superseded == False`. This applies to:

- Product list endpoint (`GET /api/v1/products/`)
- Product count/stats endpoints
- Codex contribution pipeline
- Processing queue (don't queue tasks for superseded products)

This mirrors how `is_missing` and `is_duplicate` are already filtered.
