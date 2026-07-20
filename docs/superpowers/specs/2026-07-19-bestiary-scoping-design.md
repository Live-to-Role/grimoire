# Bestiary Scoping and Review Throughput — Design

**Date:** 2026-07-19
**Status:** Approved
**Follows:** `2026-07-19-bestiary-tools-design.md` (the bestiary feature this extends)

## Problem

Extracting one 252-page bestiary produced 184 entries. Two problems surfaced immediately:

1. **Review does not scale.** Confirming entries is one `PATCH` per entry. Confirming 175 took over five minutes, because each request commits its own transaction and forces an fsync against a large database. Reads on the same endpoint take 220ms, and the queue was idle throughout — the cost is the per-request commit, not contention.

2. **Results are unscoped.** Every browse, roll, and generated table draws from every confirmed monster in the library. With one book that is merely lopsided; with several bestiaries it makes encounter tables useless, because a table meant for a woodland hex draws from every book at once.

## Goals

- Confirm or reject many entries in one request.
- Scope browsing, rolls, and tables to a chosen set of books.
- Save a whole query — books, filters, and die size — as a named favorite that regenerates a table in one click.

## Non-Goals

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

## Constraints

Inherited from the bestiary spec and the project:

- Route handlers commit explicitly — `get_db()` does not auto-commit.
- JSON-in-Text columns: `json.dumps` to store, `json.loads` to read.
- Only `review_status == "confirmed"` entries feed browse, random, and metrics. `POST /random` stays confirmed-only and must not be overridable by the request body.
- Tool output carries name/page/book pointers, short derived tags, and computed math — never stat-block prose.
- Route functions are called directly in tests with the `db` fixture; keep signatures compatible with direct invocation.
- Declare literal paths (`/books`, `/favorites`) before `/{entry_id}`-shaped routes so they are not captured by the parameterized route.

## Testing

- **Backend:** pytest, following the existing direct-call pattern in `tests/test_monsters_api.py`. Cover: bulk status happy path, invalid status → 422, empty ids, unknown ids; `product_ids` filtering across two books on both list and random; `/books` counting only confirmed entries; favorites CRUD round-trip including JSON config fidelity.
- **Frontend:** no test harness exists; `npx tsc -b` is the gate. Known pre-existing error: `Settings.tsx` unused `Shield` import.
- **Baseline:** backend is 323 passed / 6 pre-existing failures. Only new failures matter.

## Risks

- **Replacing `product_id` with `product_ids`** breaks any caller I have not accounted for. Mitigated by the endpoint being one day old with a single known consumer; a grep for `product_id` against the bestiary API confirms the surface before the change.
- **Selecting hundreds of checkboxes** could itself become the bottleneck that bulk-status was meant to remove. "Select all unflagged" is the mitigation; a filter-based bulk variant is the escape hatch if it is not enough.
