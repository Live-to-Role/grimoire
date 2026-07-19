# Bestiary Tools — Design Spec

**Date:** 2026-07-19
**Status:** Approved for planning
**Scope:** Grimoire v1 (personal use); designed for later Codex community contribution and encounter simulation

## Problem

Published bestiaries (the instigating example: Goodman Games' *Dungeon Denizens 2*) contain the content GMs need but not the *access patterns* they need at the table: environment-indexed lookup, random encounter tables, difficulty-at-a-glance. A GM who owns the book still can't answer "give me three wilderness monsters around HD 3" without paging through it.

Grimoire already owns the machinery to fix this: a library of the user's own PDFs, a text-extraction pipeline (freshly re-processed), an out-of-process job worker, and multi-provider LLM plumbing (`ai_identifier.py`). This feature builds a structured monster index over books the user owns, plus tools on top of it.

## Product principles

- **Complement, never substitute.** The tools output pointers back into the owned book (`Name — Book, p. X`), never reproduced stat blocks, flavor text, or art. Names, page numbers, tags, and computed math are facts; the protected expression stays in the PDF. A tool that is useless without the book is both legally clean and publisher-friendly.
- **Progression:** v1 personal-use in Grimoire → later, human-confirmed entries become contributable to Codex → possibly publisher-blessed companion tools. Only v1 is in scope here, but the review gate and normalized data model exist partly to serve that path.

## v1 scope

1. Mark a library product as a bestiary and run extraction against it (DCC and generic-OSR system profiles).
2. Hybrid extraction: heuristic segmentation → LLM normalization → human review/confirm UI.
3. Confirmed entries browsable/filterable by environment, HD range, system, and book.
4. Random encounter roll ("N random monsters matching filters") and rollable table generation (environment + die size → d8/d12-style table with page references).
5. Per-monster closed-form combat metrics (hit chance vs. armor tiers, average damage/round, average HP).

**Explicitly out of scope for v1** (but the data model accommodates them):

- Party profiles (hand-entered PCs) and the Monte Carlo encounter simulator (multi-monster encounters, encounter danger-level modifier, N-run death/TPK rates).
- Codex contribution of confirmed entries.
- Additional system profiles (5e is the likely next one; its regular stat blocks should slot into the same pipeline).
- A synthetic single-number "deadliness score." v1 presents honest raw metrics; special abilities (paralysis, level drain, poison) dominate real lethality and live in prose where math can't see them — they are listed, not weighted.

## Architecture

### Data model

New table `monster_entries` (migration via the existing `_ensure_columns()` pattern in `database.py`):

| Field | Notes |
|---|---|
| `id` | PK |
| `product_id` | FK to products |
| `name` | Monster name |
| `page_number` | Page in the source PDF |
| `system_profile` | `dcc` \| `osr` |
| `raw_text` | The segmented source snippet — kept for the review UI and future re-extraction |
| `ac` | Normalized **ascending** AC |
| `hd_dice` | Dice notation, e.g. `3d8+3` |
| `hp_avg` | Computed average HP |
| `attacks` | JSON list: `{name, bonus, damage_dice, damage_avg}` — `bonus` is a normalized ascending-AC attack bonus |
| `move` | Movement string |
| `special_abilities` | List of ability names/phrases (listed in UI, not simulated) |
| `environments` | Tag list (e.g. `forest`, `underground`, `swamp`) |
| `extraction_confidence` | Extractor's confidence, surfaced in review UI |
| `review_status` | `pending` \| `confirmed` \| `rejected` — **only `confirmed` entries feed the tools** |

The AC/attacks/HP/abilities subset is the **combatant statline** — deliberately monster-agnostic. v2 party members (hand-entered PCs) and the simulator reuse this exact shape with a different source; an encounter is a list of statlines plus a danger modifier.

### System profiles (code, not DB)

A small Python registry per system, each defining:

- Stat-line regex anchors and entry-header patterns for segmentation.
- Normalization: THAC0 / attack matrices / descending AC → ascending AC and attack bonus (attack bonus ≈ 20 − THAC0; conversions are per-profile since editions vary slightly).
- Armor-tier mapping: which ascending AC "unarmored / leather / chain / plate + shield" mean in that system, so metrics read naturally across editions.

Normalization happens **at extraction time**; THAC0 vs. ascending never leaks past this layer. Downstream math and the future simulator consume only the normalized model.

The canonical concept is **hit probability as a function of target defense** — not THAC0 or any edition's mechanic. For d20-family systems that function is a line, so a single normalized attack bonus encodes it losslessly (and stays human-checkable in the review UI). THAC0, attack matrices, and descending AC are merely input dialects the profiles translate. The metrics layer consumes *probabilities*, so a hypothetical non-d20 profile (2d6-over-target, dice pools) could supply a different curve without touching downstream code — noted for the future, not built now.

### Extraction pipeline (hybrid)

Runs as a queue job through the existing out-of-process worker — no LLM or CPU-heavy work inline in the API.

1. **Designate.** Per-product "Extract Monsters" action with a system-profile picker.
2. **Segment (heuristic).** Profile regexes scan the product's already-extracted page text for stat-line anchors and headers, producing candidate entries with page numbers. Tuned for high recall; sloppy precision is acceptable because the LLM and reviewer sit downstream.
3. **Normalize (LLM).** Each candidate goes to the LLM via the existing `ai_identifier.py` provider abstraction (OpenAI/Anthropic/Ollama) with a strict JSON schema and a profile-specific prompt. Environment tags are inferred from entry prose. Post-validation sanity checks: dice notation parses, AC/bonuses in plausible range, damage expressions parse. Anything failing validation is flagged, never silently kept.
4. **Review (human).** UI lists extracted entries with `raw_text` side-by-side with parsed fields; the user edits, confirms, or rejects. This gate is what makes the data trustworthy for combat math and, later, worth contributing to Codex.

### Metrics (computed on read)

Pure functions over confirmed statlines — nothing stored:

- **Hit chance vs. armor tiers:** `P(hit) = clamp((21 + bonus − tier_ac) / 20)` per profile tier.
- **Average damage/round:** Σ over attacks of `damage_avg × P(hit vs. tier)`.
- **Average HP:** the stored `hp_avg` (computed from `hd_dice` once at extraction time).

### API (under `/api/v1`)

- `POST /monsters/extract/{product_id}` — enqueue extraction (body: system profile).
- `GET /monsters` — filterable list (environment, HD range, system, product, review_status).
- `PATCH /monsters/{id}` — edit fields / set review status.
- `GET /monsters/{id}/metrics` — computed metrics.
- `POST /monsters/random` — N random confirmed monsters matching filters (also powers table generation client-side).

Route handlers commit explicitly, per project convention.

### Frontend

New "Bestiary" route: filter bar (environment, HD range, system, book), entry list with metrics panel, "Roll N random" button, and a table generator (environment + die size → rollable table, rows as `Name — Book, p. X`). Review mode surfaces pending entries for confirm/edit/reject. Gate remains `tsc -b` (no frontend test harness).

## Error handling

- Per-entry extraction failures flag and continue; one mangled stat block never kills a book's run.
- Products yielding zero candidates report that plainly ("no stat blocks recognized — is the system profile right?").
- LLM output failing schema/sanity validation lands in review as flagged-pending, never auto-confirmed.

## Testing

- pytest fixtures containing real DCC and OSR stat-block text exercising the segmenter regexes.
- Unit tests for THAC0→bonus and descending→ascending AC normalization, and for metric math.
- Normalizer contract tested with a mocked LLM client.
- Existing suite conventions: `backend/tests/`, session-scoped in-memory SQLite `db` fixture, miniconda `python -m pytest`.

## Sequencing note

This feature consumes the freshly re-processed extracted text and never touches embeddings — it can proceed before the mass re-embed without conflict. (The re-embed's gate remains the OCR re-extract queue draining, per the search-accuracy plan.)
