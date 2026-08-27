# Deep Text Search — Design

**Date:** 2026-08-26
**Status:** Implemented, but **its central premise was wrong**. Read this
correction before the rest of the document.

> ## ⚠️ Correction (2026-08-26, after implementation)
>
> **This spec argues from a claim that is not true.** It asserts below that a
> rare term past the 50,000-character cap cannot be found, because BM25 cannot
> nominate the book and "semantic similarity does not reliably recover them."
>
> Semantic recovers them fine. With the keyword body path disabled entirely,
> `Kurabanda` and `Edestekai` — terms appearing only past page 30 of *SF1
> Volturnus* — both return that book at **rank 1**. Chunk embeddings already
> covered the whole document and the Stage 2 re-rank always scored against
> them. Only the raw keyword path was blind, and that turned out not to matter.
>
> This was never verified before the spec was written. It should have been:
> one search would have settled it.
>
> **The design still shipped, and search improved — by the opposite mechanism
> to the one argued here.** The gain came from *removing* the truncated body
> text from `products_fts`, not from adding the full body back:
>
> | Configuration | hit@k | MRR | precision@k |
> |---|---|---|---|
> | Before — body text in `products_fts`, 50k cap | 50% | 0.450 | 44% |
> | Body hits fed into keyword candidates, as designed below | 50% | 0.414 | **32%** |
> | **Shipped** — body index built but not blended into ranking | **80%** | **0.505** | **84%** |
>
> Big rulebooks contain nearly every word, so body BM25 floats generic
> compendiums over real answers. Feeding *more* body text into keyword ranking
> was worse than the truncated version it replaced.
>
> **What this means for the sections below:** the schema, write path, sync,
> backfill and sweep are all as-built and correct. The **Candidate selection**
> section is not: `chunk_candidates()` exists but is deliberately *not* wired
> into `search_service`. It serves explicit phrase lookup — "where does this
> book say X, and on what page" — which is what it is genuinely good at.
>
> Full results, including corrections to three of the implementation plan's
> own instructions, are in
> `docs/superpowers/plans/2026-08-26-deep-text-search.md`.

## Problem

`update_search_vector` truncates the indexed body at 50,000 characters
(`fts_service.py:114`). Everything past that character is invisible to keyword
search.

Measured against the live library:

| | |
|---|---|
| Products with extracted text | 19,163 |
| Exceeding the 50,000-char cap | **7,259 (38%)** |
| Library text total | 1,911 M chars |
| Currently keyword-indexed | 557 M chars (**29%**) |
| Invisible to keyword search | **1,354 M chars** |

Among over-cap products the median is 121,702 characters — barely 41% indexed.
At p90 it is 544,420 (9% indexed); the largest is 3,571,095 (1.4% indexed).

This is not a scanned-book problem. Only 91 of the 7,259 affected products are
scans; the cap has been degrading keyword search across the whole library since
long before any OCR work.

**Concrete failure.** *Star Frontiers - SF1 Volturnus Planet of Mystery*
contains "Kurabanda" 228 times. Searching for it does not return the book,
because the term first appears past the cap in the indexed markdown.

> ⚠️ **Overstated.** What was verified is narrower: the FTS body column did
> not match — `extracted_text:Kurabanda` returned nothing. Full search was
> never tried. It returns the book at rank 1, and did so before any of this
> work, via the semantic path.

### Why the second stage does not save it

Search runs two stages (`search_service.search`):

1. **Stage 1 — candidates.** Document vectors (`sv_top_candidates`) unioned
   with BM25 over `products_fts` (`fts_candidates`), 150 per source.
2. **Stage 2 — chunk re-rank.** Candidates only are re-scored against
   `product_embeddings`, producing the best chunk's text and page.

Stage 2 already sees the whole document. But it only ever sees products that
Stage 1 nominated. A rare proper noun past character 50,000 can never nominate
its book via BM25 — and rare proper nouns are precisely what keyword search
exists for. Semantic similarity does not reliably recover them.

> ⚠️ **This paragraph is the error, and the whole spec rests on it.** The
> first two sentences are true. The last is not, and was assumed rather than
> tested.
>
> Stage 1 has a second source the argument ignores: the averaged document
> vector (`sv_top_candidates`), which is built from every chunk in the book.
> A term repeated 228 times pulls that vector toward itself, so the book is
> nominated on the semantic side without BM25 ever seeing the term. Measured:
> `Kurabanda` returns *SF1 Volturnus* at rank 1 with the keyword body path
> switched off.

## Root cause is shared ownership, not the constant

The cap is the second symptom of one design flaw. The first was fixed in
`038731f`: `products_fts.extracted_text` was written by `update_search_vector`
and silently blanked by the `products_fts_update` trigger, because **two
writers shared one table**. Raising the constant would leave that shared
ownership in place.

The fix is to split ownership. `products_fts` keeps metadata — which is all its
trigger ever wrote. The body moves to a table of its own, keyed by chunk.

## Approach

A standalone FTS5 table over chunk text.

The text already exists: `product_embeddings` holds 3,319,560 chunk rows with
`chunk_text`, `chunk_index`, `page_start`, and `page_end`, covering every
document with no cap. Nothing needs re-extracting. All 107 scanned books
already have chunks.

### Why standalone rather than external-content FTS5

An external-content table (`content='product_embeddings'`) would avoid
duplicating the text, and was the initial recommendation on disk grounds. It
loses on both axes that matter once disk is not a constraint:

- **Efficiency.** The embedding blob averages 2,993 bytes beside 459 bytes of
  chunk text — 6.5x the text it accompanies. SQLite reads whole rows, so every
  snippet lookup would fetch ~3,452 bytes to return 459 useful ones: 11.5 GB
  touched across 3.3 M chunks versus 1.6 GB for a lean row. Page numbers would
  also require a join back into that same fat table.
- **Headroom.** External content requires indexed text to match the content
  table exactly, or `snippet()` and offsets corrupt. A standalone table allows
  the *indexed* text to diverge from the *displayed* text. That matters here:
  the OCR output contains genuine garbage runs (`cesscerocececeenscoessceeeees`
  appears in SF1's own text). Indexing a normalized variant while showing the
  raw snippet is a lever worth keeping. It is out of scope for this spec, but
  external content forecloses it permanently.

A contentless table (`content=''`) cannot reconstruct matched text, so
`snippet()` is unavailable. Rejected.

## Design

### Schema

```sql
CREATE VIRTUAL TABLE product_chunks_fts USING fts5(
    chunk_text,
    product_id  UNINDEXED,
    chunk_index UNINDEXED,
    page_start  UNINDEXED,
    page_end    UNINDEXED
);
```

Page numbers travel with the hit, so a match returns its page with no join.

`products_fts` loses its `extracted_text` column and becomes metadata-only:
`title, file_name, publisher, game_system, product_type, description`.

### Candidate selection

> ⚠️ **Not as built.** This section was implemented, measured, and reverted:
> blending body hits into keyword candidates dropped topical precision from
> 84% to 32%. `chunk_candidates()` exists with the signature described here,
> but `search_service` does not call it. See the correction at the top.


`fts_candidates` gains chunk hits as a second keyword source. A product scores
by its **single best chunk**, matching `TOP_K_CHUNKS = 1` on the semantic side
("score a product by its single best chunk"). Metadata hits and body hits are
merged before the 150-candidate cut, so a title match and a body match compete
on the same list rather than one crowding out the other.

The best-scoring chunk also supplies a keyword-side snippet and page. Today
`best_chunk` is populated only by the semantic re-rank, so a product that
surfaces purely on keywords displays no snippet.

⚠️ **The unary `+` on the boolean filters is load-bearing and must be carried
into the new query.** Without it SQLite drives the join from
`ix_products_is_duplicate` and re-runs the MATCH once per product (~87 s per
query instead of ~0.03 s). See the comment at `fts_service.py:62`.

### Synchronisation

Chunk rows are written in one place. The chunk index is written there too, in
the same task — **not by a database trigger.**

This deviates from how `products_fts` is currently kept in sync, deliberately.
Trigger-based sync is what produced `038731f`: the trigger drifted from the
schema it served, blanked 2,800 products' indexed text, and went unnoticed for
months because nothing errored. An explicit write path is testable; a trigger
is not.

### Migration

1. Create `product_chunks_fts` in `_ensure_fts_table`, which already owns FTS
   schema (and, since `87f5039`, is the single source of truth that
   `POST /queue/fts/recreate` defers to).
2. Rebuild `products_fts` without `extracted_text`.
3. Backfill the chunk index from `product_embeddings` as queued work, reusing
   the existing queue rather than a blocking request. 3.3 M chunks is a long
   job and must be resumable.

### Required change outside the new code

`search_fts` calls `snippet(products_fts, 6, ...)`. Column 6 **is**
`extracted_text`. Dropping that column changes what column 6 means, so this
call must move to the chunk index or be removed. Missing this yields wrong
snippets rather than an error.

`update_search_vector` exists to write the body into `products_fts`. With the
body moved out, and metadata already maintained by the insert/update triggers,
its remaining job may be nothing at all. The implementation should verify this
and delete it if so — it is the function that caused `038731f`.

## Testing and success criteria

**Correctness.** The failing case is the acceptance test: searching
"Kurabanda" must return SF1 Volturnus, with a page in the low 30s. Equivalent
cases should be drawn from other over-cap books, including one in the p90 range
where under 10% is currently indexed.

**Search quality.** `backend/scripts/search_eval.py` — pinned, reproducible,
~67 s — is the gate. Measure hit@k and MRR immediately before and after; do not
quote historical figures, which have drifted twice. The change must not regress
them. An improvement is expected but is not the bar; not regressing is.

**Performance.** Query latency must stay in the same range. The `+` trick makes
the difference between 0.03 s and 87 s, so a latency check is a correctness
check, not a nicety.

**Index size.** Build the index over a subset first and extrapolate before
committing to the full backfill. Estimated ~1.5 GB of text plus ~1–1.5 GB of
index, but that is arithmetic on average row sizes, not a measurement. FTS5
overhead scales with vocabulary, and OCR noise inflates vocabulary badly —
every garbage run is unique tokens. If the measured figure lands far above
estimate, that is an argument for normalizing indexed text, which this spec
deliberately leaves out of scope.

## Out of scope

- **Normalizing OCR text before indexing.** Real, and the standalone table is
  chosen partly to keep it possible. Needs its own measurement of how much
  garbage is present and what normalization costs in recall.
- **Re-ranking or tuning constants.** `KEYWORD_RRF_WEIGHT` and friends were
  tuned against the eval harness; changing what BM25 sees may justify retuning,
  but that is a separate exercise with its own before/after measurement.
- **Chunk-level result UI.** This spec makes page and snippet available on the
  keyword path. Whether the UI grows a jump-to-page affordance is separate.

## Open question

Deleting a product must delete its chunk index rows. `product_embeddings` is
cleaned up by an ORM relationship rather than a foreign key, because SQLite
foreign-key enforcement is off in this application, so `ondelete=CASCADE` is
inert. A virtual table has no ORM relationship to hang that on. The
implementation must confirm which mechanism actually removes chunk rows today
and follow it, rather than assuming a cascade fires.
