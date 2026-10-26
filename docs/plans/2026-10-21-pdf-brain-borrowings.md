# Borrowings from pdf-brain — parked

**Date:** 2026-10-21
**Status:** Backlog. Item 1 (MCP server) is specced in
`docs/superpowers/specs/2026-10-21-mcp-server-design.md`; the rest wait.

Source: review of [joelhooks/pdf-brain](https://github.com/joelhooks/pdf-brain),
a local PDF/Markdown knowledge base with Ollama embeddings, libSQL vectors,
FTS5 and an agent-first CLI. Grimoire's retrieval is ahead of it (two-stage
search, RRF, page-aware chunks, query interpreter, OCR, eval harness); what
follows is the short list of things it does that Grimoire does not. Ranked by
value for effort.

## 2. Query embedding cache

**What.** In-process LRU for query embeddings keyed by
`(provider, model, text)`. pdf-brain: `EmbeddingProvider.embed()` wrapper,
size from `PDF_BRAIN_QUERY_EMBED_CACHE_SIZE`, default 256.

**Why.** `search_service` caches the search-vector matrix and candidate chunk
matrices, but every query still round-trips to Ollama for its own
embedding. Repeated or refined queries, `search_pack` fan-out, and
`scripts/search_eval.py` all pay it again.

**How.** Wrap `generate_embeddings` for the single-query path only (never for
document chunks). Invalidate on provider or model change. Size ~256.

**Measure.** Wall-clock on a second run of `search_eval.py`.

## 3. Paragraph-first chunking with hyphenation repair

**What.** pdf-brain's `chunkText` (`src/services/PDFExtractor.ts`): normalise
newlines, join `inter-\nnational`, rebuild paragraphs, then fill chunks
paragraph by paragraph, fall back to sentences, hard-split only as a last
resort, drop chunks under 20 chars.

**Why.** `embeddings._chunks_with_spans` is a fixed 1000-char window that
backs up to the nearest sentence end. Chunks that straddle a paragraph or
table boundary embed as a blend of two topics.

**Caveat.** Grimoire's extractors (pymupdf4llm, pdfplumber path) already
rebuild paragraphs, so the gain may be small. Do not ship without a number.

**Measure.** `search_eval.py --compare` against a baseline run; keep only if
hit@k or MRR moves. Requires re-embedding, so pair with item 4.

## 4. Chunker version stamped on embeddings

**What.** pdf-brain stamps `metadata.chunker = {id, version, chunkSize,
chunkOverlap}` on each document, and `doctor` / `rechunk --dry-run` list
documents whose stamp no longer matches the current chunker.

**Why.** `product_embeddings` records `embedding_model` and
`/re-embed-mismatched` acts on it, but nothing records how the chunks were
cut. The moment item 3 lands, old and new chunking coexist silently.

**How.** `chunker_version` column on `product_embeddings` (or fold into the
existing model string); extend `re-embed-mismatched` to treat a chunker
mismatch like a model mismatch; dry-run count in `/semantic/status`.

## 5. Tag review queue with duplicate detection

**What.** pdf-brain's enrichment prompt is given the existing vocabulary
and told to propose new concepts *only* for topics it lacks. Proposals are
held for review (`taxonomy proposed` / `accept` / `reject`), and each one is
checked against existing concepts by embedding similarity and then a
one-word LLM judge (`DUPLICATE` or `DISTINCT`) before acceptance.

**Why.** `TAG_SUGGESTION_PROMPT` returns free strings per category, so
"undead", "the undead" and "undead-horror" accumulate as three tags. At
19 000 products that is real sprawl.

**How.** Keep Grimoire's flat tags; borrow only the review queue and the
dedupe check. Pass the current tag list into the prompt; store suggestions
as `pending` on `product_tags` (or a `tag_proposals` table); surface a
review list in Library Management. Skip the SKOS hierarchy, and keep Codex
as the vocabulary for product fields.

## 6. Explicit score semantics in results

**What.** Every pdf-brain hit carries `scoreType`, `rawScore`, `matchType`
and a normalised `score` in 0..1.

**Why.** Phase 4 of `2026-03-13-semantic-search-improvements.md` wants
relevance indicators in the UI. `search_service` already returns `score`
(normalised to the top hit) and `match_type`; what is missing is the raw
chunk cosine and the raw BM25 rank, which is what a "why did this match"
tooltip needs.

**How.** Add `raw_semantic` and `raw_keyword` to each result item. No
ranking change.

## Deliberately not borrowed

- **One HNSW index over every chunk.** pdf-brain reports ~48 GB of vector
  index for 500k chunks. Grimoire's candidate-then-rerank design loads
  chunk matrices only for nominated products; keep it.
- **Partial vector indexes per tag; gated embedding queue with WAL
  checkpoints.** Solve libSQL and PGlite problems Grimoire does not have.
- **RAPTOR-style clustering and cluster summaries.** Experimental there,
  heavy here.
- **Markdown ingestion.** Covered by `2026-08-23-multi-format-scanning-design.md`
  with the PDF-only Codex guard. One detail worth lifting when the
  flat-text phase lands: pdf-brain's `MarkdownExtractor` chunks by heading
  section and keeps code blocks intact.
- **JSON envelope, HATEOAS hints, agent CLI.** MCP tool descriptions and
  structured results cover this.
