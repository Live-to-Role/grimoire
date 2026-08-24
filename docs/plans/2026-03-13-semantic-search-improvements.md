# Semantic Search Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve semantic search result quality by enriching embeddings with metadata, applying existing library filters during semantic search, blending keyword (BM25) and vector scores for hybrid search, and surfacing relevance scores in the UI.

**Architecture:** Four phased improvements, each independently shippable: (1) metadata-enriched embeddings (already done), (2) pass existing filters through to semantic search, (3) hybrid BM25 + cosine scoring via reciprocal rank fusion, (4) UI relevance indicators and low-result guidance. Each phase builds on the previous but is functional on its own.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite FTS5, numpy, React, TypeScript, React Query v5

**Prior work:** `docs/plans/2026-03-11-integrated-semantic-search-plan.md` (original semantic search implementation)

---

## Phase 1: Metadata-Enriched Embeddings (COMPLETE)

Already implemented in this session. `build_metadata_preamble()` in `embeddings.py` prepends title, game_system, publisher, type, author, setting, genre, series, level range, description, themes, and tags to extracted text before chunking and embedding. Both the queue handler and single-product embed endpoint use it.

**Action required:** Re-generate all embeddings via Library Management > Generate Embeddings to pick up the new metadata preamble.

---

## Phase 2: Apply Library Filters to Semantic Search

### Task 1: Add filter parameters to the semantic search request schema

**Files:**
- Modify: `backend/grimoire/api/routes/semantic.py:69-75`
- Test: `backend/tests/test_semantic_search.py`

- [ ] **Step 1: Write failing test for filter parameters**

```python
# In backend/tests/test_semantic_search.py
from grimoire.api.routes.semantic import SemanticSearchRequest

def test_semantic_search_request_accepts_filters():
    """SemanticSearchRequest accepts optional filter fields."""
    req = SemanticSearchRequest(
        query="undead adventure",
        game_system="Dungeon Crawl Classics",
        product_type="adventure",
        level_min=1,
        level_max=3,
        publisher="Goodman Games",
    )
    assert req.game_system == "Dungeon Crawl Classics"
    assert req.level_min == 1
    assert req.level_max == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_semantic_search.py::test_semantic_search_request_accepts_filters -v`
Expected: FAIL — `SemanticSearchRequest` does not accept `game_system`

- [ ] **Step 3: Add filter fields to SemanticSearchRequest**

In `backend/grimoire/api/routes/semantic.py`, update the request model:

```python
class SemanticSearchRequest(BaseModel):
    """Request for semantic search."""
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(10, ge=1, le=100)
    threshold: float = Field(0.5, ge=0.0, le=1.0)
    provider: str | None = Field(None)
    model: str | None = Field(None)
    # Metadata filters (applied post-vector-search)
    game_system: str | None = Field(None)
    product_type: str | None = Field(None)
    genre: str | None = Field(None)
    publisher: str | None = Field(None)
    author: str | None = Field(None)
    level_min: int | None = Field(None, ge=0)
    level_max: int | None = Field(None, ge=0)
    tags: str | None = Field(None, description="Comma-separated tag IDs")
    collection: int | None = Field(None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_semantic_search.py::test_semantic_search_request_accepts_filters -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/api/routes/semantic.py backend/tests/test_semantic_search.py
git commit -m "feat: add filter fields to SemanticSearchRequest schema"
```

---

### Task 2: Apply filters to semantic search results on the backend

**Files:**
- Modify: `backend/grimoire/api/routes/semantic.py:271-277` (the product fetch query in `/search`)
- Test: `backend/tests/test_semantic_search.py`

- [ ] **Step 1: Write failing test**

This test verifies that filter conditions are added to the products query. Since we can't easily do a full integration test without embeddings, test that the filter-building helper works:

```python
# In backend/tests/test_semantic_search.py
from grimoire.api.routes.semantic import build_semantic_filter_conditions, SemanticSearchRequest
from grimoire.models.product import Product

def test_build_semantic_filter_conditions():
    """build_semantic_filter_conditions returns SQLAlchemy conditions for active filters."""
    req = SemanticSearchRequest(
        query="test",
        game_system="DCC",
        level_min=1,
        level_max=5,
    )
    conditions = build_semantic_filter_conditions(req)
    # Should have game_system condition + level range conditions
    assert len(conditions) >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_semantic_search.py::test_build_semantic_filter_conditions -v`
Expected: FAIL — `build_semantic_filter_conditions` does not exist

- [ ] **Step 3: Implement filter builder and apply in search endpoint**

Add a helper function in `backend/grimoire/api/routes/semantic.py` (before the search endpoint):

```python
def build_semantic_filter_conditions(request: SemanticSearchRequest) -> list:
    """Build SQLAlchemy filter conditions from semantic search request."""
    conditions = []
    if request.game_system:
        conditions.append(Product.game_system == request.game_system)
    if request.product_type:
        conditions.append(Product.product_type == request.product_type)
    if request.genre:
        conditions.append(Product.genre == request.genre)
    if request.publisher:
        conditions.append(Product.publisher == request.publisher)
    if request.author:
        conditions.append(Product.author == request.author)
    if request.level_min is not None:
        conditions.append(
            (Product.level_range_max >= request.level_min) | (Product.level_range_max.is_(None))
        )
    if request.level_max is not None:
        conditions.append(
            (Product.level_range_min <= request.level_max) | (Product.level_range_min.is_(None))
        )
    return conditions
```

Then update the products_query in the `/search` endpoint (around line 271) to apply these conditions.

**Important:** `.where(*conditions)` fails when the list is empty. Always include a base condition or guard:

```python
        # Fetch full product data for matched IDs, applying filters
        filter_conditions = build_semantic_filter_conditions(request)

        # Handle tag filtering via subquery (avoids double-join with selectinload)
        if request.tags:
            tag_ids = [int(t.strip()) for t in request.tags.split(",") if t.strip()]
            if tag_ids:
                tag_subq = select(ProductTag.product_id).where(ProductTag.tag_id.in_(tag_ids))
                filter_conditions.append(Product.id.in_(tag_subq))

        # Handle collection filtering via subquery
        if request.collection:
            from grimoire.models.collection import CollectionProduct
            coll_subq = select(CollectionProduct.product_id).where(
                CollectionProduct.collection_id == request.collection
            )
            filter_conditions.append(Product.id.in_(coll_subq))

        products_query = (
            select(Product)
            .where(Product.id.in_(matched_ids))
            .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
        )
        if filter_conditions:
            products_query = products_query.where(*filter_conditions)
```

Also increase `top_k` sent to `search_product_vectors` to `request.top_k * 3` to account for results filtered out by metadata, then truncate after filtering:

```python
        # Fetch more candidates than requested since filters will reduce results
        search_top_k = request.top_k * 3 if filter_conditions or request.tags or request.collection else request.top_k
        matches = search_product_vectors(
            query_vector, search_vectors, search_top_k, request.threshold
        )
```

And after building results, truncate to `request.top_k`:

```python
        results = results[:request.top_k]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_semantic_search.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/api/routes/semantic.py backend/tests/test_semantic_search.py
git commit -m "feat: apply metadata filters to semantic search results"
```

---

### Task 3: Pass filters from frontend to semantic search API

**Files:**
- Modify: `frontend/src/api/semantic.ts`
- Modify: `frontend/src/pages/Library.tsx:87-97`

- [ ] **Step 1: Update semanticSearch() to accept and pass filter params**

In `frontend/src/api/semantic.ts`:

```typescript
import type { ProductFilters } from './products';

export async function semanticSearch(
  query: string,
  topK: number = 20,
  filters: Partial<ProductFilters> = {},
): Promise<SemanticSearchResponse> {
  const response = await apiClient.post<SemanticSearchResponse>('/semantic/search', {
    query,
    top_k: topK,
    threshold: 0.3,
    game_system: filters.game_system || undefined,
    product_type: filters.product_type || undefined,
    genre: filters.genre || undefined,
    publisher: filters.publisher || undefined,
    author: filters.author || undefined,
    level_min: filters.level_min ? Number(filters.level_min) : undefined,
    level_max: filters.level_max ? Number(filters.level_max) : undefined,
    tags: filters.tags || undefined,
    collection: filters.collection || undefined,
  });
  return response.data;
}
```

- [ ] **Step 2: Pass effectiveFilters to semanticSearch in Library.tsx**

In `frontend/src/pages/Library.tsx`, update the semantic search query (around line 87-97):

```typescript
  // Semantic search query
  const {
    data: semanticData,
    isLoading: semanticLoading,
    error: semanticError,
  } = useQuery({
    queryKey: ['semantic-search', activeSearch, effectiveFilters],
    queryFn: () => semanticSearch(activeSearch, 20, effectiveFilters),
    enabled: activeSearch.length > 0 && searchSemantic,
    staleTime: 60000,
  });
```

- [ ] **Step 3: Verify filter drawer still works in semantic mode**

Manual test: enable semantic search, open filter drawer, select a game system, search. Results should be filtered.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/semantic.ts frontend/src/pages/Library.tsx
git commit -m "feat: pass library filters through to semantic search"
```

---

## Phase 3: Hybrid Search (BM25 + Vector Fusion)

### Task 4: Add a hybrid search service function

**Files:**
- Create: `backend/grimoire/services/hybrid_search.py`
- Test: `backend/tests/test_hybrid_search.py`

- [ ] **Step 1: Write failing test for reciprocal rank fusion**

```python
# backend/tests/test_hybrid_search.py
"""Tests for hybrid search score fusion."""
from grimoire.services.hybrid_search import reciprocal_rank_fusion


def test_rrf_merges_two_ranked_lists():
    """reciprocal_rank_fusion merges two ranked lists, boosting items in both."""
    # (product_id, score) tuples, already sorted by score desc
    semantic_results = [(1, 0.95), (3, 0.80), (5, 0.70)]
    keyword_results = [(3, 5.0), (2, 4.0), (1, 3.0)]
    merged = reciprocal_rank_fusion(semantic_results, keyword_results, k=60)
    ids = [pid for pid, _ in merged]
    # Product 3 appears in both lists at good ranks — should be #1 or #2
    assert 3 in ids[:2]
    # All 4 unique products should appear
    assert set(ids) == {1, 2, 3, 5}


def test_rrf_empty_keyword_list():
    """reciprocal_rank_fusion works when keyword results are empty."""
    semantic = [(1, 0.9), (2, 0.8)]
    merged = reciprocal_rank_fusion(semantic, [], k=60)
    assert len(merged) == 2
    assert merged[0][0] == 1


def test_rrf_empty_semantic_list():
    """reciprocal_rank_fusion works when semantic results are empty."""
    keyword = [(1, 5.0), (2, 3.0)]
    merged = reciprocal_rank_fusion([], keyword, k=60)
    assert len(merged) == 2
    assert merged[0][0] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_hybrid_search.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement reciprocal rank fusion**

Create `backend/grimoire/services/hybrid_search.py`:

```python
"""Hybrid search combining semantic vectors with keyword (BM25) scores."""


def reciprocal_rank_fusion(
    semantic_results: list[tuple[int, float]],
    keyword_results: list[tuple[int, float]],
    k: int = 60,
    semantic_weight: float = 1.0,
    keyword_weight: float = 1.0,
) -> list[tuple[int, float]]:
    """
    Merge two ranked result lists using Reciprocal Rank Fusion (RRF).

    RRF scores each item as: sum(weight / (k + rank)) across lists.
    Items appearing in both lists get boosted naturally.

    Args:
        semantic_results: (product_id, score) sorted by score desc
        keyword_results: (product_id, score) sorted by score desc
        k: RRF constant (higher = less emphasis on top ranks; 60 is standard)
        semantic_weight: Weight multiplier for semantic ranks
        keyword_weight: Weight multiplier for keyword ranks

    Returns:
        Merged (product_id, rrf_score) sorted by rrf_score desc
    """
    scores: dict[int, float] = {}

    for rank, (pid, _) in enumerate(semantic_results):
        scores[pid] = scores.get(pid, 0.0) + semantic_weight / (k + rank + 1)

    for rank, (pid, _) in enumerate(keyword_results):
        scores[pid] = scores.get(pid, 0.0) + keyword_weight / (k + rank + 1)

    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return merged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_hybrid_search.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/hybrid_search.py backend/tests/test_hybrid_search.py
git commit -m "feat: add reciprocal rank fusion for hybrid search"
```

---

### Task 5: Add hybrid mode to the semantic search endpoint

**Files:**
- Modify: `backend/grimoire/api/routes/semantic.py`
- Modify: `backend/grimoire/services/fts_service.py` (may need to expose a simpler search function)
- Test: `backend/tests/test_hybrid_search.py`

- [ ] **Step 1: Add `hybrid` flag to SemanticSearchRequest**

```python
class SemanticSearchRequest(BaseModel):
    # ... existing fields ...
    hybrid: bool = Field(False, description="Blend keyword (BM25) + vector scores")
```

- [ ] **Step 2: Implement hybrid path in the `/search` endpoint**

In the semantic search endpoint, after computing `matches` from vector search, add a hybrid branch:

```python
        if request.hybrid and request.query:
            from grimoire.services.fts_service import search_fts
            from grimoire.services.hybrid_search import reciprocal_rank_fusion

            # Get BM25 keyword results
            try:
                fts_results = await search_fts(
                    db, request.query,
                    game_system=request.game_system,
                    product_type=request.product_type,
                    limit=request.top_k * 3,
                )
                # Note: search_fts returns dicts with "id" (not "product_id")
                keyword_matches = [
                    (r["id"], r["relevance_score"]) for r in fts_results
                ]
            except Exception:
                logger.warning("FTS5 search failed during hybrid search, falling back to pure semantic")
                keyword_matches = []

            # Fuse rankings
            matches = reciprocal_rank_fusion(matches, keyword_matches)
            matches = matches[:search_top_k]

            # Normalize RRF scores to 0-1 range for consistent UI display
            if matches:
                max_score = matches[0][1]  # highest RRF score (list is sorted desc)
                if max_score > 0:
                    matches = [(pid, score / max_score) for pid, score in matches]
```

This goes right after the `search_product_vectors` call and before the product fetch query.

- [ ] **Step 3: Write integration-level test**

```python
# In backend/tests/test_hybrid_search.py
def test_rrf_handles_duplicate_ids():
    """Items in both lists get boosted, not duplicated."""
    semantic = [(1, 0.9), (2, 0.8), (3, 0.7)]
    keyword = [(2, 5.0), (3, 4.0), (4, 3.0)]
    merged = reciprocal_rank_fusion(semantic, keyword)
    ids = [pid for pid, _ in merged]
    # No duplicates
    assert len(ids) == len(set(ids))
    # Product 2 is high in both — should rank well
    assert ids.index(2) <= 1
```

- [ ] **Step 4: Run all tests**

Run: `cd backend && python -m pytest tests/test_hybrid_search.py tests/test_semantic_search.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/api/routes/semantic.py backend/tests/test_hybrid_search.py
git commit -m "feat: add hybrid search mode blending BM25 + vector scores"
```

---

### Task 6: Enable hybrid mode from the frontend

**Files:**
- Modify: `frontend/src/api/semantic.ts`
- Modify: `frontend/src/pages/Library.tsx`

- [ ] **Step 1: Pass hybrid flag in semanticSearch()**

Update `frontend/src/api/semantic.ts` — add `hybrid: true` to the POST body:

```typescript
export async function semanticSearch(
  query: string,
  topK: number = 20,
  filters: Partial<ProductFilters> = {},
): Promise<SemanticSearchResponse> {
  const response = await apiClient.post<SemanticSearchResponse>('/semantic/search', {
    query,
    top_k: topK,
    threshold: 0.3,
    hybrid: true,
    game_system: filters.game_system || undefined,
    // ... rest of filters unchanged
  });
  return response.data;
}
```

Hybrid is always-on for now. A toggle can be added later if users want pure semantic mode.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/semantic.ts
git commit -m "feat: enable hybrid search by default in frontend"
```

---

## Phase 4: UI Relevance Indicators and Search Guidance

### Task 7: Display relevance scores on search result cards

**Files:**
- Modify: `frontend/src/components/ProductCard.tsx`
- Modify: `frontend/src/components/ProductGrid.tsx`
- Modify: `frontend/src/pages/Library.tsx`

- [ ] **Step 1: Add optional `score` prop to ProductCard**

In `frontend/src/components/ProductCard.tsx`, update the props interface:

```typescript
interface ProductCardProps {
  product: Product;
  onClick?: (product: Product) => void;
  viewMode?: 'grid' | 'list';
  selectable?: boolean;
  selected?: boolean;
  onSelectionChange?: (productId: number, selected: boolean) => void;
  score?: number;  // Semantic search relevance score (0-1)
}
```

Update the destructuring:

```typescript
export function ProductCard({ product, onClick, viewMode = 'grid', selectable, selected, onSelectionChange, score }: ProductCardProps) {
```

- [ ] **Step 2: Render a relevance badge in grid mode**

In the grid card, add a score badge inside the cover image wrapper div (the `aspect-[3/4]` div).

**Important:** There is an existing extraction status indicator at `absolute top-2 right-2` (lines 228-237 of ProductCard.tsx). Use `bottom-2 left-2` instead to avoid overlap:

```tsx
        {score != null && (
          <div
            className="absolute bottom-2 left-2 rounded-full px-2 py-0.5 text-xs font-medium"
            style={{
              backgroundColor: 'var(--color-surface)',
              color: 'var(--color-text-secondary)',
              border: '1px solid var(--color-border)',
              opacity: 0.9,
            }}
            title={`Relevance: ${Math.round(score * 100)}%`}
          >
            {Math.round(score * 100)}%
          </div>
        )}
```

Place this after the extraction status indicator block and before the closing `</div>` of the cover wrapper.

- [ ] **Step 3: Render score in list mode**

In the list view (around line 130, near the metadata badges), add:

```tsx
        {score != null && (
          <span
            className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
            style={{
              backgroundColor: 'var(--color-accent-light)',
              color: 'var(--color-accent)',
            }}
          >
            {Math.round(score * 100)}% match
          </span>
        )}
```

- [ ] **Step 4: Add scoreMap prop to ProductGrid**

`Library.tsx` renders `ProductGrid`, not `ProductCard` directly. Update `ProductGrid.tsx` to accept and forward scores:

In `frontend/src/components/ProductGrid.tsx`, add to the interface:

```typescript
interface ProductGridProps {
  products: Product[];
  onProductClick?: (product: Product) => void;
  viewMode?: 'grid' | 'list';
  hasNextPage?: boolean;
  isFetchingNextPage?: boolean;
  fetchNextPage?: () => void;
  selectable?: boolean;
  selectedIds?: Set<number>;
  onSelectionChange?: (productId: number, selected: boolean) => void;
  scoreMap?: Record<number, number>;  // product_id -> relevance score
}
```

Update the destructuring to include `scoreMap`, and pass it through in the map (around line 92-101):

```typescript
          <ProductCard
            key={product.id}
            product={product}
            onClick={onProductClick}
            viewMode={viewMode}
            selectable={selectable}
            selected={selectedIds?.has(product.id)}
            onSelectionChange={onSelectionChange}
            score={scoreMap?.[product.id]}
          />
```

- [ ] **Step 5: Build scoreMap in Library.tsx and pass to ProductGrid**

In `Library.tsx`, build a score lookup from semantic results:

```typescript
  // Build score map from semantic results
  const scoreMap = useMemo(() => {
    if (!semanticData?.results) return undefined;
    const map: Record<number, number> = {};
    for (const r of semanticData.results) {
      map[r.id] = r.score;
    }
    return map;
  }, [semanticData]);
```

Then pass it to `ProductGrid` (around line 411):

```typescript
              <ProductGrid
                products={displayProducts}
                onProductClick={handleProductClick}
                viewMode={viewMode}
                hasNextPage={!isSearching && hasNextPage}
                isFetchingNextPage={isFetchingNextPage}
                fetchNextPage={fetchNextPage}
                selectable={true}
                selectedIds={selectedIds}
                onSelectionChange={handleSelectionChange}
                scoreMap={searchSemantic ? scoreMap : undefined}
              />
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ProductCard.tsx frontend/src/components/ProductGrid.tsx frontend/src/pages/Library.tsx
git commit -m "feat: display relevance scores on semantic search results"
```

---

### Task 8: Show guidance when semantic search returns few results

**Files:**
- Modify: `frontend/src/pages/Library.tsx`

- [ ] **Step 1: Add a low-results guidance message**

In Library.tsx, after the search results count display, add guidance when semantic search returns fewer than 3 results:

```tsx
{searchSemantic && semanticData && semanticData.total_matches < 3 && activeSearch && (
  <div
    className="rounded-lg p-3 text-sm"
    style={{
      backgroundColor: 'var(--color-surface-raised)',
      color: 'var(--color-text-secondary)',
      border: '1px solid var(--color-border)',
    }}
  >
    <p className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
      Few results found. Try:
    </p>
    <ul className="mt-1 ml-4 list-disc space-y-0.5">
      <li>Describing the content differently (e.g., "horror themed dungeon with zombies")</li>
      <li>Using the filter drawer to narrow by game system first, then searching</li>
      <li>Switching to Content search for exact phrase matching</li>
    </ul>
  </div>
)}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Library.tsx
git commit -m "feat: show search guidance when semantic results are sparse"
```

---

## Phase 5: Weighted Metadata Chunk (Optional Enhancement)

### Task 9: Weight the metadata-enriched first chunk higher in the averaged vector

**Files:**
- Modify: `backend/grimoire/models/product_search_vector.py`
- Test: `backend/tests/test_product_search_vector.py` (if exists, else `backend/tests/test_semantic_search.py`)

- [ ] **Step 1: Write failing test**

```python
# In the appropriate test file
from grimoire.models.product_search_vector import compute_weighted_average_vector

def test_weighted_average_boosts_first_chunk():
    """compute_weighted_average_vector weights first chunk higher."""
    # First chunk is [1, 0], rest are [0, 1]
    vectors = [[1.0, 0.0], [0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]
    uniform = compute_weighted_average_vector(vectors, metadata_weight=1.0)
    boosted = compute_weighted_average_vector(vectors, metadata_weight=3.0)
    # Boosted version should have higher first dimension
    assert boosted[0] > uniform[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_semantic_search.py::test_weighted_average_boosts_first_chunk -v`
Expected: FAIL — function does not exist

- [ ] **Step 3: Implement weighted average**

In `backend/grimoire/models/product_search_vector.py`, add:

```python
def compute_weighted_average_vector(
    vectors: list[list[float]],
    metadata_weight: float = 2.0,
) -> list[float]:
    """Compute weighted average of chunk vectors, boosting the first (metadata) chunk.

    Args:
        vectors: List of embedding vectors (first is assumed to contain metadata preamble)
        metadata_weight: Weight multiplier for the first chunk (default 2x)
    """
    if not vectors:
        return []
    if len(vectors) == 1:
        return vectors[0]

    arr = np.array(vectors, dtype=np.float32)
    weights = np.ones(len(vectors), dtype=np.float32)
    weights[0] = metadata_weight
    weighted = np.average(arr, axis=0, weights=weights)
    return weighted.tolist()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_semantic_search.py::test_weighted_average_boosts_first_chunk -v`
Expected: PASS

- [ ] **Step 5: Use weighted average in queue processor**

In `backend/grimoire/services/queue_processor.py`, in `handle_embed_task`, replace:

```python
    from grimoire.models.product_search_vector import ProductSearchVector, compute_average_vector
    ...
    avg_vector = compute_average_vector(chunk_vectors)
```

with:

```python
    from grimoire.models.product_search_vector import ProductSearchVector, compute_average_vector, compute_weighted_average_vector
    ...
    avg_vector = compute_weighted_average_vector(chunk_vectors, metadata_weight=2.0)
```

Do the same in the `/embed/{product_id}` endpoint in `semantic.py`.

- [ ] **Step 6: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/models/product_search_vector.py backend/grimoire/services/queue_processor.py backend/grimoire/api/routes/semantic.py backend/tests/test_semantic_search.py
git commit -m "feat: weight metadata chunk higher in averaged product vectors"
```

---

## Summary of Phases

| Phase | Tasks | Impact | Requires Re-embed |
|-------|-------|--------|-------------------|
| 1. Metadata preamble | Done | High — embeddings now capture game system, publisher, etc. | Yes |
| 2. Filter passthrough | Tasks 1-3 | High — users can narrow semantic results with existing filters | No |
| 3. Hybrid BM25+vector | Tasks 4-6 | High — keyword queries like "Dungeon Crawl Classics" work well | No |
| 4. UI indicators | Tasks 7-8 | Medium — helps users understand and improve their searches | No |
| 5. Weighted metadata | Task 9 | Low-Medium — subtle improvement to ranking quality | Yes |

**Recommended order:** Phases 2-4 first (no re-embed needed), then re-embed once for Phases 1+5 together.
