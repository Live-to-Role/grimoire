# Integrated Semantic Search Design

## Problem

The app has two search systems — FTS (full-text search) and semantic (AI embeddings) — but only FTS is accessible from the Library search bar. Semantic search endpoints exist in the backend but are never surfaced in the UI. Users build embeddings from the Settings page expecting natural language search, but can't use it.

Additionally, API keys are shared across features. A user may want Anthropic for product identification but Ollama for search, with no way to control this per-feature.

## Design

### Three mutually exclusive search modes

The Library search bar supports three modes via pill toggle buttons:

| Mode | Toggle | Behavior | Endpoint | Placeholder |
|------|--------|----------|----------|-------------|
| Title/metadata | Neither active | Debounced, instant | `GET /products?search=...` | "Search titles..." |
| Content (FTS) | "Content" active | Enter to submit | `GET /search?q=...&search_content=true` | "Search in PDF content..." |
| Semantic | "Semantic" active | Enter to submit | `POST /semantic/search` | "Search with AI..." |

The "Semantic" pill is disabled with tooltip when semantic search is not available (no provider configured or no embeddings generated).

### Per-product averaged embeddings

Current implementation stores per-chunk embeddings (~50 chunks per product). Searching 17k+ products by brute-force cosine similarity on all chunks would require loading ~850k vectors into memory (1-5GB) and take 10-30+ seconds.

Instead, compute a per-product embedding (average of chunk vectors) at embedding generation time. Store in a `product_embedding` column on `ProductEmbedding` or a new `product_search_vectors` table.

Search flow:
1. Embed the query string via configured provider (~200-500ms)
2. On first search, load all product-level vectors into a numpy matrix and cache in memory (~26MB for 17k products)
3. Single `np.dot` for cosine similarity across all products (<50ms)
4. Return top-k results
5. Cache invalidated when embeddings are added/removed

Per-chunk embeddings are retained for potential future use (page-level matching).

This division plays to each system's strengths:
- **FTS** for specific content queries: "encounter table with kobolds"
- **Semantic** for conceptual queries: "creepy adventure in a wetland for beginners"

### New DB setting: `semantic_search_provider`

Values: `none` (default), `ollama`, `openai`, `local`

Controls which provider embeds search queries at query time. Separate from the provider used for product identification or embedding generation.

### New endpoint: `GET /semantic/search-status`

Lightweight endpoint for the frontend to determine whether to enable the Semantic toggle:

```json
{
  "enabled": true,
  "provider": "ollama",
  "has_embeddings": true,
  "embedded_count": 142
}
```

### Modified endpoint: `POST /semantic/search`

Reads `semantic_search_provider` from DB instead of accepting provider as a request parameter. Returns error if setting is `none` or provider unavailable.

### Settings page addition

In the existing "Semantic Search (AI Embeddings)" section of LibraryManagement, add a "Search Provider" dropdown:

- **Options:** Disabled (default), Ollama, OpenAI, Local (sentence-transformers)
- **Visibility:** Only configured/available providers are selectable; others greyed out
- **Helper text:** "Choose which provider embeds your search queries. This is separate from the provider used for product identification."

Saves `semantic_search_provider` to the DB settings table.

### Frontend search bar changes

- Add "Semantic" pill button next to "Content"
- Mutually exclusive: clicking one deactivates the other
- Semantic pill disabled when `search-status.enabled` is false
- Results displayed in same `ProductGrid` component
- Result count: `5 results for "swamp adventures" (semantic search)`
