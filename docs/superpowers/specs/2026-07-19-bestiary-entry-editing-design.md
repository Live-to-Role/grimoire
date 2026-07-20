# Bestiary Entry Editing — Design

**Date:** 2026-07-19
**Status:** Approved
**Follows:** `2026-07-19-bestiary-tools-design.md`, `2026-07-19-bestiary-scoping-design.md`

## Problem

Extracted entries can only be partially corrected, and cannot be created at all.

1. **No way to create an entry.** The API exposes `PATCH /{entry_id}` and `POST /bulk-status`; nothing creates a `MonsterEntry`. When segmentation merges several creatures into one row, or misses a monster entirely, there is no recovery inside the app.

   Observed: entry #124 held *Cone Snail*, *Giant Cone Snail* and *Giant Clam* in a single row, because all three sit as `**Bold:**` stat blocks under one `# Mollusks` header. Splitting it required a direct database write. This is an accepted consequence of high-recall segmentation and will recur on any book that groups creatures that way.

2. **The edit surface is three fields.** Review mode offers inline Name, AC and HD editors. Move, attacks, special abilities and environments cannot be corrected at all.

3. **`PATCH` cannot clear a field.** `patch_entry` applies each value behind `if value is not None`, so an explicit `null` is indistinguishable from "not sent" and is ignored. There is no way to express "this monster has no AC". The inline AC editor works around this by skipping blank input entirely — a workaround that a full edit form cannot use.

## Goals

- Create a monster entry by hand, deriving the same computed fields extraction derives.
- Edit every user-owned field on an existing entry, including clearing one.
- Duplicate an entry as the starting point for a new one, so splitting a merged row does not mean retyping shared context.
- Delete an entry created in error.

## Non-Goals

- **Free-form custom fields.** A survey of the 416 extracted entries shows the fixed schema already absorbs the awkward cases as free text: `hd_dice` holds `4d8 per 8 tentacles`, `1d10 per head`, `2d6 or 4d6`; `damage_dice` holds `1d3 plus stun`, `1d8 plus 1d4 Agility drain`, `disease`. Only the *derived* numerics go null, and the entry is flagged. Storage is not the gap; UI is. Custom fields would also be invisible to the metrics math, creating a second unstructured source of truth.
- **Per-system field definitions.** Supporting 5e's Challenge, proficiency bonus and ability scores means changing the model, the extraction prompt and the metrics layer. That belongs with the 5e profile spec.
- **Editing `raw_text` or `system_profile`.** `raw_text` is provenance — the source excerpt an entry was derived from. `system_profile` selects the armor tiers the metrics are computed against, so changing it silently invalidates every number shown.
- **User-editable `flags`.** Flags are machine-generated validation output. Leaving them machine-only keeps "unflagged" meaningful as a selection criterion.

## Design

### 1. Create

`POST /api/v1/monsters`

```json
{
  "product_id": 13, "page_number": 109, "system_profile": "dcc",
  "name": "Giant Clam", "ac": 26, "hd_dice": "5d6", "move": "0'",
  "attacks": [], "special_abilities": [], "environments": ["aquatic"],
  "raw_text": "optional source excerpt"
}
```

`product_id`, `name` and `system_profile` are required; `system_profile` is validated against `PROFILES` and `product_id` against an existing product (404 otherwise).

The server derives `hd_value`, `hp_avg` and each attack's `damage_avg` with the same `grimoire.utils.dice` functions the extractor uses, and runs the same validation to produce `flags`. A hand-entered entry with no attacks gets `no_attacks` exactly as an extracted one does. Clients never compute derived fields.

**`extraction_confidence` is `null`.** These are hand-transcribed, not model output, and inventing a score would misrepresent them. Consequence, deliberately accepted: the "select all unflagged" control requires `confidence >= 0.8`, so hand-created entries are never swept up by it and always need an explicit tick.

**`review_status` is `"confirmed"`.** A human authored the entry, so it has already had the scrutiny the review gate exists to apply.

That has a UI consequence which must be handled rather than discovered: creating an entry while the list is filtered to `pending` means the new entry does not appear, because it is confirmed. On success the form reports the entry as created and confirmed and offers to switch the view to it, rather than silently returning to a list that does not contain it.

### 2. Edit

`PATCH /{entry_id}` keeps its path and partial semantics, but distinguishes *absent* from *explicitly null* using Pydantic's `model_fields_set`: a field present in the request body is applied even when its value is `null`; a field not present is left alone.

This is what makes "clear the AC" expressible, and it preserves the existing inline editors, which send one key at a time.

Editable: `name`, `page_number`, `ac`, `hd_dice`, `attacks`, `move`, `special_abilities`, `environments`, `review_status`. Derived fields are recomputed on every change to their source, as they are today.

### 3. Delete

`DELETE /api/v1/monsters/{entry_id}` → `{"deleted": true}`, 404 if absent.

Distinct from rejecting. Reject records a judgement about the source ("this is not a monster") and is reversible; delete removes a row that should never have existed, such as a mistyped duplicate.

### 4. Frontend

An **entry form modal**, not an inline expansion. The existing inline editors use uncontrolled `defaultValue` + `onBlur` inputs, which retain stale DOM values across list re-renders — a bug already hit once on this page. A modal with controlled state avoids that class of problem, and a form this size does not belong in a list row.

Entry points:

| Control | Behaviour |
|---|---|
| **Add entry** (Bestiary header) | Empty form; book picker, page, profile, then fields |
| **Edit** (per row) | Form populated from the entry |
| **Duplicate** (per row) | Form prefilled with the source's book, page, profile and `raw_text`; stats cleared; name suffixed " (copy)" so an unedited save is obvious |

Attacks are add/remove rows of name, bonus, damage. Freeform damage such as `1d3 plus stun` is accepted and simply yields no `damage_avg`, matching how extraction already treats it.

The book picker reuses the `MultiCombobox` option shape (`{id, label, count}`) in single-select mode, or a plain select over `GET /monsters/books` — it must not require the book to already have entries, since creating the first entry for a book is a valid case. Use `GET /products?search_mode=name` for the lookup instead.

## Constraints

- Route handlers commit explicitly — `get_db()` does not auto-commit.
- JSON-in-Text columns: `json.dumps` to store, `json.loads` to read.
- Declare literal paths before `/{entry_id}`-shaped routes.
- Route functions are called directly in tests with the `db` fixture; keep signatures compatible with direct invocation.
- **Never use a bare `= Query(...)` / `= Depends(...)` default on a route function this codebase invokes directly in tests** — the Python default becomes the `Query` object rather than `None`. Use the `Annotated[T, Query()] = None` form. (This defect was found during the scoping phase.)
- Only `review_status == "confirmed"` entries feed browse, random and metrics.

## Testing

- **Backend:** pytest, direct-call pattern. Cover: create happy path; create derives `hp_avg`/`hd_value`/`damage_avg` identically to extraction (a `3d6` entry must yield 10.5); create rejects an unknown `product_id` (404) and an unknown `system_profile` (400); create sets `confirmed` and null confidence; PATCH clears a field when null is sent explicitly; PATCH leaves a field alone when absent; delete removes the row; delete of an unknown id is 404.
- **Frontend:** `npx tsc -b` (baseline is clean, no expected errors).
- **Baseline:** backend 345 passed / 6 pre-existing failures as of the scoping phase — re-verify before starting, as this repo has had parallel work land mid-session more than once.

## Risks

- **Auto-confirming hand-created entries bypasses the review gate.** A typo enters browse and random rolls immediately. Mitigated by delete and by edit; judged acceptable because a human authored the row.
- **`model_fields_set` changes PATCH semantics.** Any existing caller that sends an explicit null expecting it to be ignored would now clear that field. The only caller is this app's Bestiary page, whose inline editors send a single non-null key at a time, so the surface is known — but it warrants a grep before the change.
- **Duplicate carries `raw_text` from its source**, so a split entry's review pane shows text covering all the creatures the original held. Preferred over slicing the text per creature, which risks cutting shared rules; reviewing with too much context beats reviewing with the wrong context.
