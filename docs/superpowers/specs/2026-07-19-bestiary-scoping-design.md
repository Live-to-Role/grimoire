# Bestiary Scoping and Review Throughput — Design

**Date:** 2026-07-19
**Status:** Approved
**Follows:** `2026-07-19-bestiary-tools-design.md` (the bestiary feature this extends)

## Problem

Extracting one 252-page bestiary produced 184 entries. Two problems surfaced immediately:

1. **Review does not scale.** Confirming entries is one `PATCH` per entry. Confirming 175 took over five minutes, because each request commits its own transaction and forces an fsync against a large database. Reads on the same endpoint take 220ms, and the queue was idle throughout — the cost is the per-request commit, not contention.

2. **Results are unscoped.** Every browse, roll, and generated table draws from every confirmed monster in the library. With one book that is merely lopsided; with several bestiaries it makes encounter tables useless, because a table meant for a woodland hex draws from every book at once.

3. **Extracting with the wrong system profile fails silently.** *5E HÂRN Bestiary* (product 3031) was queued with the DCC profile. Both existing profiles find zero candidates in it — 5e stat blocks read `Armor Class 11` / `Hit Points 51 (6d10 + 18)` / `Challenge 2`, with no `Init +N` or `HD NdN` for the anchors to match. The handler found nothing, saved nothing, and returned success, so the queue reported "completed" with no indication anything was wrong. Nothing was spent (no candidates means no LLM calls) and no rows were written, but the user had no way to learn that the extraction was impossible.

4. **Extraction is unreachable from where books live.** Queueing a book means copying its title out of the Library, switching to the Bestiary page, searching for it again, and picking it from a list. The book detail modal — where the user already is — offers no way to do it.

## Goals

- Confirm or reject many entries in one request.
- Scope browsing, rolls, and tables to a chosen set of books.
- Save a whole query — books, filters, and die size — as a named favorite that regenerates a table in one click.
- Refuse an extraction that cannot work, and warn when the chosen profile looks wrong.
- Queue an extraction directly from the book detail modal.

## Non-Goals

- **A D&D 5e system profile.** The user owns 5e bestiaries, but supporting them is real work — a new anchor, Challenge ratings, proficiency-derived attack bonuses, and `Hit Points 51 (6d10 + 18)` parsing that the current `hd_dice` / `hp_avg` fields do not model. Its own spec. This spec only makes the failure legible.
- **Exclude-mode book filtering.** Include-only (whitelist) covers the current library size. Revisit when there are enough bestiaries that ticking the ones you want is worse than ticking the ones you don't.
- **Fixing `total_dpr` over-counting.** DCC statlines list attacks as alternatives (`bite +3 melee (1d6) or claw +5 melee (1d4)`), but the metrics service sums every attack, overstating damage for those monsters. Real defect, but it needs a schema change to record whether attacks are alternatives or simultaneous. Separate spec.
- **Snapshotting rolled results.** A favorite stores the query, not the monsters it produced. Re-running re-rolls.

## Design

### 1. Bulk review status

`POST /api/v1/monsters/bulk-status`

```json
{ "ids": [12, 13, 14], "review_status": "confirmed" }
```

One `UPDATE ... WHERE id IN (...)`, one commit. Returns `{"updated": n}`.

- `review_status` validated against `pending | confirmed | rejected`; 422 otherwise, matching `PATCH /{entry_id}`.
- Unknown ids are silently skipped; `updated` reflects rows actually changed, so the caller can detect a mismatch.
- Empty `ids` returns `{"updated": 0}` without touching the database.

Bulk reject comes free from the same endpoint.

**UI (review mode only):** a checkbox per row, plus **select all** and **select all unflagged**. The second is the important one — of 184 entries, 175 had no validation flags and were confirmed unchanged after spot-checking. A footer bar shows `Confirm N selected` / `Reject N selected`.

"Unflagged" means `flags == []` **and** `extraction_confidence >= 0.8`. Both conditions are required: entry #124 ("Cone Snail / Giant Cone Snail / Giant Clam") carried no flags yet was the single genuinely bad row in the batch — three creatures merged under one shared header — and its 0.65 confidence was the only signal distinguishing it. Selecting on flags alone would have swept it in.

### 2. Multi-book filter

Replace the single `product_id` filter with a repeatable `product_ids` parameter on `GET /monsters` and in the `POST /monsters/random` body. Empty or omitted means all books.

Replacing rather than keeping both: `/monsters` shipped the same day as this spec and the Bestiary page is its only consumer, so there is no compatibility surface to preserve. `POST /monsters/extract/{product_id}` keeps its path parameter — it acts on one book by definition.

**New endpoint:** `GET /api/v1/monsters/books` → `[{"product_id": 13, "title": "...", "count": 175}]`, ordered by title. The multi-select needs it, and it doubles as a "what is actually in my bestiary" overview.

Takes an optional `review_status` parameter defaulting to `confirmed`, and `count` reflects that status. Without it the book list would be wrong in review mode: a freshly extracted book has only `pending` entries, so a confirmed-only list would offer no books to filter by precisely when you are reviewing that book. The filter bar passes whatever review status is active.

**UI:** a multi-select in the filter bar rendering selections as removable chips.

### 3. Saved favorites

A favorite is a named query plus the die size, so one click regenerates a prepared table.

**Storage:** new table `bestiary_favorites`:

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(200), not null | user-supplied |
| `config` | Text, not null | JSON, per the `ProcessingQueue.config` convention |
| `created_at` / `updated_at` | DateTime | `server_default=func.now()`, `onupdate` |

`config` holds the full query: `product_ids`, `environment`, `system_profile`, `hd_min`, `hd_max`, `q`, `table_size`.

Stored in the database rather than `localStorage`: favorites are curated campaign prep and should not die with browser data. A new table needs no `_ensure_columns()` entry — `Base.metadata.create_all` in `init_db()` creates it, the same way `monster_entries` was added.

`review_status` is deliberately excluded from `config`. It is a workflow toggle, not part of a query about monsters.

**API:**

| Endpoint | Purpose |
|---|---|
| `GET /monsters/favorites` | list, newest first |
| `POST /monsters/favorites` | create from `{name, config}` |
| `PATCH /monsters/favorites/{id}` | rename, or overwrite `config` with the current query |
| `DELETE /monsters/favorites/{id}` | remove |

**UI:** a "★ Save current query" control, and a favorites strip. Clicking a favorite applies its filters and die size; a **Run** button applies and rolls in one action.

### 4. Extraction guard

`POST /monsters/extract/{product_id}` runs a dry-run segmentation across every registered profile before queueing. This is free: segmentation is pure regex over already-extracted text, with no LLM involved.

Content, not metadata, is the signal. `game_system` is unreliable — product 255 is labelled Old-School Essentials but is byte-identical to product 13, a DCC book. Metadata is used only to phrase the error message, never to decide.

| Condition | Behaviour |
|---|---|
| Chosen profile finds 0 candidates | `400`, nothing queued. Message names the supported systems, and identifies the likely system from `game_system` when it maps to something known. |
| Chosen profile finds < half the best-scoring profile, **and** the best finds ≥ 20 | Queue it, return `{"queued": true, "warning": "..."}` naming both counts. |
| Otherwise | Queue normally. |

The response carries per-profile counts in all cases, so a caller can show "found 210 stat blocks" before committing.

The mismatch threshold is deliberately loose. It exists to catch DCC-versus-5e-scale errors, not to adjudicate DCC versus OSR: the OSR anchor also matches DCC stat lines (a known, accepted property from the bestiary spec), so those two counts do not separate cleanly and a strict rule would refuse legitimate work.

**Handler change, independent of the guard:** `handle_monster_extract_task` returns success when segmentation yields zero candidates. It must raise `TaskError` instead. The guard makes this rare, but a book whose text is re-extracted after queueing can still reach the worker with nothing to segment, and "completed, 0 results" is the exact silent failure this spec exists to remove.

### 5. Extract from the Library

An **"Extract as bestiary"** action in the product detail modal, beside the existing processing controls.

Deliberately **not** on the modal's `extract` tab. That tab belongs to the older structured-extraction prototype (`/structured/all/{id}`), which is unrelated to the bestiary and is what the user mistook for this feature.

Flow: the button calls the dry-run preview, then shows an inline confirmation with the candidate count and a profile picker, pre-selected from the book's `game_system` when it maps to a known profile. Confirming queues the extraction; on success the panel links through to the Bestiary review view.

Shown only when `text_extracted` is true, reusing the "extract text first" hint pattern of the neighbouring controls.

Because this makes the extract endpoint serve two callers, the dry-run belongs in the route, not duplicated in either UI.

## Constraints

Inherited from the bestiary spec and the project:

- Route handlers commit explicitly — `get_db()` does not auto-commit.
- JSON-in-Text columns: `json.dumps` to store, `json.loads` to read.
- Only `review_status == "confirmed"` entries feed browse, random, and metrics. `POST /random` stays confirmed-only and must not be overridable by the request body.
- Tool output carries name/page/book pointers, short derived tags, and computed math — never stat-block prose.
- Route functions are called directly in tests with the `db` fixture; keep signatures compatible with direct invocation.
- Declare literal paths (`/books`, `/favorites`) before `/{entry_id}`-shaped routes so they are not captured by the parameterized route.

## Testing

- **Backend:** pytest, following the existing direct-call pattern in `tests/test_monsters_api.py`. Cover: bulk status happy path, invalid status → 422, empty ids, unknown ids; `product_ids` filtering across two books on both list and random; `/books` counts respecting `review_status`; favorites CRUD round-trip including JSON config fidelity; guard refusing a zero-candidate profile with 400, guard warning on a lopsided count, guard staying silent on a clean match; handler raising `TaskError` on zero candidates.
- **Guard fixtures:** use inline markdown fixtures shaped like real stat blocks (a DCC inline stat line, and a 5e block using `Armor Class` / `Hit Points` / `Challenge`) rather than reading real PDFs, so the tests stay fast and independent of the user's library.
- **Frontend:** no test harness exists; `npx tsc -b` is the gate. Known pre-existing error: `Settings.tsx` unused `Shield` import.
- **Baseline:** backend is 323 passed / 6 pre-existing failures. Only new failures matter.

## Risks

- **Replacing `product_id` with `product_ids`** breaks any caller I have not accounted for. Mitigated by the endpoint being one day old with a single known consumer; a grep for `product_id` against the bestiary API confirms the surface before the change.
- **Selecting hundreds of checkboxes** could itself become the bottleneck that bulk-status was meant to remove. "Select all unflagged" is the mitigation; a filter-based bulk variant is the escape hatch if it is not enough.
- **The dry-run makes enqueue non-instant.** Segmenting a 252-page book took roughly 1.5s in measurement, across every registered profile. Acceptable for a button press, but the endpoint no longer returns immediately and a double-click would repeat the work. Mitigation is to disable the button while the request is in flight; caching the result is not worth the invalidation problem, since a book's text can change under it.
- **The mismatch threshold is a guess.** `< half the best, best ≥ 20` is calibrated against exactly two data points (210 candidates on a DCC book, 0 on a 5e one). It may warn on legitimate extractions or stay quiet on bad ones. It only ever warns, never blocks, so the cost of being wrong is a dismissable message.
