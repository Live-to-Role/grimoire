# Search Accuracy Design — Page-Anchored Chunks, Query Interpretation, Two-Stage Retrieval

**Date:** 2026-07-08
**Status:** Approved
**Goal:** The Library semantic search returns weak results for natural queries like "Undead adventure for 3rd level characters." Make relevance good, and finalize the extraction storage format *before* the full-library re-extract/re-embed pass so that pass produces final-form, page-anchored data.

## Diagnosis (verified against the live DB, 2026-07-08)

- 18,358 products. `ProductEmbedding` covers 18,344 — but `/semantic/search` searches `ProductSearchVector` (per-product *averaged* vectors), which has only 12,657 rows. ~31% of the library is invisible to the search bar today.
- The chunk table is split cleanly: 12,657 products have all-`nomic-embed-text` chunks (768-dim) + a search vector; 5,687 products have only stale `all-MiniLM-L6-v2` chunks (384-dim) and no search vector. No mixed-model products.
- 3.69M chunk vectors total (~9 GB float32). Brute-force in-memory chunk search is infeasible; a two-stage candidate/re-rank design is not.
- Averaged whole-book vectors dilute topical signal — the biggest relevance limiter.
- The search bar sends fixed `threshold: 0.3, hybrid: true` and parses nothing from the query; "3rd level" is never mapped to `level_range_min/max`. `level_range` is populated on only 3,022 products (16%).
- `interpret_nl_query` (LLM query parsing) exists but only serves `POST /semantic/query`, which loads every chunk row into memory — broken at this scale.
- Extraction stores one flat markdown string per book (`pymupdf4llm.to_markdown(...)`, `text_extractor.py:500`). No page boundaries survive — blocking page references for search results and for the planned structured-entity database.

## Out of scope / owned elsewhere

- **Coverage repair & mass re-embed:** another session (branch `feat/oversized-guard`) lands the oversized guard + smallest-first queue ordering, then triggers a full-library re-extract/re-embed. This feature does no re-embedding. **Hard sequencing constraint: the mass pass must not start until Phase 0 of this feature merges**, or it writes 3.7M chunks in the old un-anchored format.
- **Structured-entity database** (monsters/traps/tables with source-page refs): separate future spec. It consumes the page anchors Phase 0 produces; nothing else here depends on it.
- Grimoire is local-only, single-user. No multi-tenant or deployment concerns.

## Architecture Overview

Four legs, one branch:

- **Phase 0 — extraction storage format** (merge-blocking for the mass pass): page-anchored markdown, page-tagged chunks, chunk size 1000/100.
- **Phase 1 — query interpretation**: heuristic parser (always) + optional cloud-LLM refinement → real filters; interpretation chips in the UI.
- **Phase 2 — two-stage retrieval**: candidate union (averaged vectors ∪ BM25) → chunk-level re-rank; threshold moves to chunk scores; search logic extracted from `routes/semantic.py` (978 lines) into a new `services/search_service.py`.
- **Supporting tasks**: DCC level backfill script; golden-query eval harness.

## Phase 0 — Page-Anchored Extraction & Chunking

### Extraction storage

- The pymupdf4llm path switches to `to_markdown(..., page_chunks=True)`. The extracted-text JSON gains a `"pages"` list as the source of truth:
  `{"pages": [{"page": 1, "markdown": "..."}, ...], ...existing keys...}` (page numbers 1-based).
- The pdfplumber-layout and OCR paths already iterate page-by-page; they emit `pages` too.
- `get_extracted_text()` becomes the single compat accessor: joins `pages` when present, falls back to the legacy flat `"markdown"` key. FTS, embedding, and all other readers go through it — zero migration for old files.

### Chunking

- New `chunk_text_with_pages(pages, chunk_size, overlap) -> list[(text, page_start, page_end)]`: concatenate page texts with tracked character offsets, run the **existing** `chunk_text` algorithm over the joined text (identical boundary behavior), then map each chunk's char range back to a page range. Cross-page chunks get a real range.
- The metadata preamble (unchanged content, `build_metadata_preamble`) becomes chunk(s) with `page_start = page_end = NULL`.
- `ProductEmbedding` gains nullable `page_start`, `page_end` integer columns via the established `_ensure_columns()` pattern in `database.py`.
- Both embed paths (`handle_embed_task` in `queue_processor.py` and `POST /semantic/embed/{id}` / `embed-batch` in `routes/semantic.py`) use the page-aware chunker when `pages` exist, falling back to flat chunking (NULL pages) otherwise.
- **Chunk size: 1000 chars, overlap 100** (was 500/50) — the `chunk_text` defaults, `handle_embed_task`'s hardcoded `500, 50`, and `EmbedProductRequest.chunk_size`'s default all move to the new values. Rationale: nomic-embed-text takes 8k tokens so ~250-token chunks stay topical; halves chunk count (~3.7M → ~1.8M) and therefore stage-2 re-rank I/O; pairs better with top-3-mean scoring than tiny fragments. Old 500-char chunks keep working during the transition — nothing checks chunk length.

## Phase 1 — Query Interpretation

New `services/query_interpreter.py`, called on the search path when `interpret: true` (new request field, default true).

### Heuristic pass (always runs)

Table-driven regexes extract, and strip matched constraint phrases from the query to form `semantic_query`:

- **Levels:** "3rd level", "level 3", "levels 2-4", "level 2 to 4", "for level 0 characters" → `level_min`/`level_max`. A single level sets both. Level 0 is a real value, never treated as missing.
- **Game system:** alias map = curated aliases ("dcc" → the DB's Dungeon Crawl Classics value, "5e"/"fifth edition" → its DB value, "pf2e", "osr", ...) merged with distinct `game_system` values from the DB (loaded once per process, cached). Case-insensitive.
- **Product type:** keyword map ("adventure"/"module" → Adventure, "bestiary", "sourcebook", "setting", ...).

Topical words stay in the semantic query even when they also set a filter ("adventure" sets product_type AND remains in `semantic_query`; "undead" is never a filter).

### LLM refinement (optional)

- Runs only if an Anthropic or OpenAI key is configured (env or DB settings, same lookup as today). One call, 5s timeout, result LRU-cached per query string.
- Model: current Haiku-class model — exact id verified against the claude-api reference at implementation time (NOT the retired `claude-3-haiku-20240307` used by today's `interpret_nl_query`).
- Output validated before use: levels clamped to 0–30; game_system/product_type must match known DB values or are dropped; `semantic_query` must be non-empty.
- Any failure or timeout → the heuristic result stands. Search never blocks on LLM availability.

### Filter semantics — lenient vs strict

- **Interpreted filters are lenient:** `(column == value) OR (column IS NULL)` — a misparse or unlabeled product must not vanish silently (level coverage is 16%; type/system coverage partial).
- **Explicit FilterDrawer filters stay strict**, as today.
- On conflict (user set a drawer filter the interpreter also extracted), the explicit value wins and the interpreted one is discarded.

### Interpretation chips (frontend)

- The search response carries `interpretation`: extracted filters, refined `semantic_query`, and `source` ("heuristic" | "llm").
- The Library results header renders removable chips ("Level 3", "System: DCC").
- Removing a chip re-issues the search with `interpret: false` plus the remaining interpreted filters passed as explicit filters — deterministic, no partial re-interpretation.

## Phase 2 — Two-Stage Retrieval

New `services/search_service.py` owns the flow; the `/semantic/search` route handler becomes a thin wrapper.

1. **Interpret** (per Phase 1) → merged filters + `semantic_query`; embed `semantic_query` (provider from settings, unchanged).
2. **Pre-filter:** evaluate all filter conditions SQL-side once → `allowed_ids` set (`None` when unfiltered). Filters constrain candidate gathering, not just post-hoc trimming.
3. **Stage 1 — candidates:** top 150 averaged-vector matches (restricted to `allowed_ids`, no threshold) ∪ top 150 BM25 (`search_fts`, post-filtered by `allowed_ids`), capped at 200 products — all SV candidates kept, remainder filled from BM25 in rank order. The SV matrix gets a real in-memory cache (12.7k × 768 float32 ≈ 39 MB), invalidated by the existing `invalidate_vector_cache()` — today's code reloads every SV row per search.
4. **Stage 2 — chunk re-rank:** load `ProductEmbedding` rows for candidate ids where `embedding_dim` matches the query vector (stale MiniLM chunks skipped by construction). Product score = mean of top-3 chunk cosine similarities (max when fewer than 3 chunks). Per-product chunk matrices in a bounded LRU cache (keyed product_id + model), invalidated alongside the SV cache.
5. **Fuse:** `reciprocal_rank_fusion(chunk_ranking, bm25_ranking)`; weights are named tunable constants, tuned via the eval harness.
6. **Threshold on meaningful scores:** minimum best-chunk similarity (initial 0.45, eval-tuned) applies to semantic candidates. Products with no valid chunks survive on BM25 rank alone (graceful mid-re-embed degradation). If zero search vectors exist at all, fall back to pure FTS results instead of returning nothing.
7. **Respond:** per result — product payload (as today), `score`, `matched_page` + `snippet` from the best chunk, `match_type` ("semantic" | "keyword" | "both"); plus the `interpretation` object.

### API surface

- `POST /semantic/search` request: `+ interpret: bool = true`. The frontend's hardcoded `threshold: 0.3` is dropped; the backend owns the threshold default (its meaning changed to chunk-level similarity).
- Response: `+ interpretation`, per-result `matched_page`, `snippet`, `match_type`.
- `POST /semantic/query`: deleted if nothing in the frontend calls it (verify at implementation), else rewired as a thin wrapper over `search_service`.
- `/semantic/similar/{id}` and embed/status endpoints unchanged.

### Frontend

- `api/semantic.ts`: pass `interpret`, drop `threshold`, type the new response fields.
- Library results header: interpretation chips (Phase 1).
- Result cards: matched-page snippet line ("matched p. 47: ...").
- Gate: `npx tsc -b` from `frontend/` (one pre-existing Settings.tsx 'Shield' error is baseline).

## Supporting Tasks

### DCC level backfill

- `backend/scripts/data/dcc_module_levels.csv` — checked-in snapshot of the Wikipedia "List of Dungeon Crawl Classics modules" tables: module number, title, level_min, level_max.
- `backend/scripts/backfill_dcc_levels.py`:
  - Candidate products: `game_system` matches DCC or title/filename contains "DCC".
  - Match by module number regex first (e.g. "DCC #67", "DCC 067"), normalized fuzzy title match second.
  - Writes `level_range_min/max` only where **both are currently NULL**. Level 0 is a real value. Idempotent.
  - `--dry-run` prints the match table without writing. Ambiguous matches and unmatched modules are listed, never guessed.

### Golden-query eval harness

- `backend/scripts/search_golden.yaml`: entries `{query, expect: [title substrings or product ids], k}`. Ships with 3–4 seeded examples; the user fills in ~10–20 real queries with expected books before tuning starts.
- `backend/scripts/search_eval.py`: calls `search_service` directly against the live DB (read-only; requires Ollama up for query embedding). Reports hit@k and MRR per query and overall. `--save`/`--compare` snapshot files so tuning runs show deltas.
- All tuning tasks (RRF weights, threshold, top-3 vs max scoring) are gated on harness numbers, not vibes.

## Error Handling

- Ollama unreachable → 503 with a clear message (unchanged).
- LLM interpreter failure/timeout → heuristic interpretation, search proceeds.
- FTS5 failure → semantic-only (existing behavior, kept).
- Zero search vectors → FTS-only fallback.
- Legacy extracted JSON (no `pages`) → flat-markdown accessor path; embeds get NULL page anchors.
- Stale MiniLM chunks and mixed chunk sizes → handled by construction (dimension filter; offset mapping is size-agnostic).

## Testing

- **Unit:** `chunk_text_with_pages` offset→page mapping (single-page, cross-page, preamble NULL pages); interpreter heuristics (table-driven query→filters cases incl. "3rd level", "levels 2-4", level 0, alias hits, no-match passthrough); lenient-vs-strict filter builder; top-3-mean scoring; RRF fusion; DCC matcher (number hit, fuzzy hit, ambiguous → skip).
- **Integration:** `search_service` against the in-memory DB fixture with `generate_embeddings` monkeypatched to a deterministic fake — full flow: interpret → candidates → re-rank → fuse → respond. FTS fixture covers the union and FTS-only fallback paths.
- **Baselines:** backend 222 passed / 6 pre-existing failures (`C:/Users/mkemi/miniconda3/python.exe -m pytest` from `backend/`); frontend `npx tsc -b` with one pre-existing Settings.tsx error. Don't fix pre-existing failures.
- **Final gate:** eval harness before/after numbers + a manual UI pass.

## Alternatives Considered

- **ANN index over all chunks (sqlite-vec / hnswlib):** highest quality ceiling, rejected for now — new native dependency on Windows, 8–11 GB index, and constant rebuild churn while the mass re-embed rewrites the library. Right architecture for Folio later.
- **Query-side-only tuning (no chunk retrieval):** cheapest, rejected — leaves the biggest limiter (averaged whole-book vectors) untouched.
- **Ollama-based query interpretation:** rejected in favor of heuristics + optional cloud LLM — adds 1–3s latency per search and needs a chat model pulled; heuristics cover the common patterns at zero latency.
