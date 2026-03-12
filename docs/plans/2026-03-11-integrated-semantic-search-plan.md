# Integrated Semantic Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Surface semantic (AI embedding) search in the Library search bar alongside the existing title and FTS content search modes, with a per-feature provider setting so users can choose which AI provider handles search queries independently from identification.

**Architecture:** Add a `semantic_search_provider` DB setting, a lightweight `/semantic/search-status` endpoint, per-product averaged embeddings for fast search at scale (~17k products), a "Semantic" toggle in the Library search bar, and a provider dropdown in the Settings page.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, numpy, React, TypeScript, React Query v5

**Design doc:** `docs/plans/2026-03-11-integrated-semantic-search-design.md`

---

### Task 1: Add `semantic_search_provider` setting and `search-status` endpoint

**Files:**
- Modify: `backend/grimoire/api/routes/semantic.py`
- Test: `backend/tests/test_semantic_search_status.py`

**Step 1: Write the failing test**

```python
"""Tests for semantic search-status endpoint."""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from grimoire.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_search_status_default_disabled(client, db):
    """search-status returns enabled=false when no provider is configured."""
    async with client as c:
        response = await c.get("/api/v1/semantic/search-status")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["provider"] == "none"


@pytest.mark.asyncio
async def test_search_status_with_provider(client, db):
    """search-status returns enabled=true when provider is set and has embeddings."""
    from grimoire.models import Setting
    setting = Setting(key="semantic_search_provider", value='"ollama"')
    db.add(setting)
    await db.commit()

    with patch("grimoire.api.routes.semantic.check_provider_available", return_value=True):
        with patch("grimoire.api.routes.semantic._count_embedded_products", return_value=5):
            async with client as c:
                response = await c.get("/api/v1/semantic/search-status")
    data = response.json()
    assert data["enabled"] is True
    assert data["provider"] == "ollama"
    assert data["has_embeddings"] is True
    assert data["embedded_count"] == 5
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_semantic_search_status.py -v`
Expected: FAIL — `search-status` endpoint does not exist yet

**Step 3: Write minimal implementation**

Add to `backend/grimoire/api/routes/semantic.py`:

```python
async def check_provider_available(provider: str) -> bool:
    """Check if a specific embedding provider is available."""
    if provider == "none":
        return False
    providers = await _get_embedding_providers()
    return providers.get(provider, False)


async def _count_embedded_products(db: AsyncSession) -> int:
    """Count products that have embeddings."""
    result = await db.execute(
        select(ProductEmbedding.product_id).distinct()
    )
    return len(result.scalars().all())


@router.get("/search-status")
async def semantic_search_status(db: DbSession) -> dict:
    """Lightweight status check for the Library search bar."""
    import json
    from grimoire.models import Setting

    # Read semantic_search_provider setting
    result = await db.execute(
        select(Setting).where(Setting.key == "semantic_search_provider")
    )
    setting = result.scalar_one_or_none()
    provider = json.loads(setting.value) if setting else "none"

    if provider == "none":
        return {
            "enabled": False,
            "provider": "none",
            "has_embeddings": False,
            "embedded_count": 0,
        }

    available = await check_provider_available(provider)
    embedded_count = await _count_embedded_products(db)

    return {
        "enabled": available and embedded_count > 0,
        "provider": provider,
        "has_embeddings": embedded_count > 0,
        "embedded_count": embedded_count,
    }
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_semantic_search_status.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/grimoire/api/routes/semantic.py backend/tests/test_semantic_search_status.py
git commit -m "feat: add semantic search-status endpoint and provider setting"
```

---

### Task 2: Per-product averaged embeddings — storage and computation

**Files:**
- Create: `backend/grimoire/models/product_search_vector.py`
- Modify: `backend/grimoire/models/__init__.py`
- Modify: `backend/grimoire/database.py` (add table to ensure)
- Modify: `backend/grimoire/api/routes/semantic.py` (update embed endpoint to compute average)
- Test: `backend/tests/test_product_search_vector.py`

**Step 1: Write the failing test**

```python
"""Tests for per-product search vector computation."""
import numpy as np
import pytest
from grimoire.models.product_search_vector import ProductSearchVector


def test_search_vector_roundtrip():
    """Vector can be stored and retrieved."""
    vec = ProductSearchVector(product_id=1, embedding_model="test", embedding_dim=3)
    original = [0.1, 0.2, 0.3]
    vec.set_vector(original)
    retrieved = vec.get_vector()
    np.testing.assert_array_almost_equal(retrieved, original)


def test_average_vectors():
    """Average of chunk vectors produces correct result."""
    from grimoire.models.product_search_vector import compute_average_vector
    chunks = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    avg = compute_average_vector(chunks)
    expected = [1/3, 1/3, 1/3]
    np.testing.assert_array_almost_equal(avg, expected)
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_product_search_vector.py -v`
Expected: FAIL — module does not exist

**Step 3: Write minimal implementation**

Create `backend/grimoire/models/product_search_vector.py`:

```python
"""Per-product averaged embedding for fast semantic search."""
from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, String
from grimoire.database import Base
import numpy as np


def compute_average_vector(chunk_vectors: list[list[float]]) -> list[float]:
    """Average a list of chunk embedding vectors into one product vector."""
    matrix = np.array(chunk_vectors, dtype=np.float32)
    return np.mean(matrix, axis=0).tolist()


class ProductSearchVector(Base):
    """One averaged embedding per product for fast semantic search."""

    __tablename__ = "product_search_vectors"

    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    vector = Column(LargeBinary, nullable=False)
    embedding_model = Column(String(100), nullable=False)
    embedding_dim = Column(Integer, nullable=False)

    def get_vector(self) -> list[float]:
        if self.vector is not None:
            return np.frombuffer(self.vector, dtype=np.float32).tolist()
        return []

    def set_vector(self, vec: list[float]):
        self.vector = np.array(vec, dtype=np.float32).tobytes()
        self.embedding_dim = len(vec)
```

Add `ProductSearchVector` to `backend/grimoire/models/__init__.py` imports.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_product_search_vector.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/grimoire/models/product_search_vector.py backend/grimoire/models/__init__.py backend/tests/test_product_search_vector.py
git commit -m "feat: add ProductSearchVector model for per-product embeddings"
```

---

### Task 3: Compute averaged vector when embeddings are generated

**Files:**
- Modify: `backend/grimoire/api/routes/semantic.py` — update `embed_product` and `embed_batch` to compute and store averaged vector after generating chunk embeddings
- Modify: `backend/grimoire/services/queue_processor.py` — if embedding tasks compute via queue, also compute average there
- Test: `backend/tests/test_product_search_vector.py` (extend)

**Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_embed_product_creates_search_vector(client, db):
    """Embedding a product also creates a per-product search vector."""
    # Create a product with extracted text
    # Call embed endpoint
    # Verify ProductSearchVector row exists with correct dimensions
    pass  # Implement with actual product fixture
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_product_search_vector.py::test_embed_product_creates_search_vector -v`

**Step 3: Implement**

In `embed_product()` in `semantic.py`, after storing chunk embeddings and before `await db.commit()`:

```python
from grimoire.models.product_search_vector import ProductSearchVector, compute_average_vector

# Compute and store per-product averaged vector
chunk_vectors = [emb_result.embedding for emb_result in embeddings]
avg_vector = compute_average_vector(chunk_vectors)

# Upsert search vector
existing_sv = await db.execute(
    select(ProductSearchVector).where(ProductSearchVector.product_id == product_id)
)
sv = existing_sv.scalar_one_or_none()
if sv:
    sv.set_vector(avg_vector)
    sv.embedding_model = embeddings[0].model
else:
    sv = ProductSearchVector(
        product_id=product_id,
        embedding_model=embeddings[0].model,
        embedding_dim=len(avg_vector),
    )
    sv.set_vector(avg_vector)
    db.add(sv)
```

Apply the same pattern in `embed_batch()` and any queue processor embedding path.

**Step 4: Run tests**

Run: `cd backend && python -m pytest tests/ -v`

**Step 5: Commit**

```bash
git add backend/grimoire/api/routes/semantic.py backend/grimoire/services/queue_processor.py
git commit -m "feat: compute averaged search vector on embed"
```

---

### Task 4: Fast numpy-based semantic search using averaged vectors

**Files:**
- Modify: `backend/grimoire/services/embeddings.py` — add cached matrix search
- Modify: `backend/grimoire/api/routes/semantic.py` — update `/search` to use averaged vectors and read `semantic_search_provider`
- Test: `backend/tests/test_semantic_search.py`

**Step 1: Write the failing test**

```python
"""Tests for fast semantic search with averaged vectors."""
import numpy as np
import pytest
from grimoire.services.embeddings import search_product_vectors


def test_search_product_vectors_returns_top_k():
    """search_product_vectors returns top-k products by cosine similarity."""
    query = [1.0, 0.0, 0.0]
    product_vectors = {
        1: [1.0, 0.0, 0.0],   # exact match
        2: [0.0, 1.0, 0.0],   # orthogonal
        3: [0.7, 0.7, 0.0],   # partial match
    }
    results = search_product_vectors(query, product_vectors, top_k=2)
    assert len(results) == 2
    assert results[0][0] == 1  # best match
    assert results[1][0] == 3  # second best
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_semantic_search.py -v`

**Step 3: Implement**

Add to `backend/grimoire/services/embeddings.py`:

```python
# In-memory cache for product search vectors
_vector_cache: dict[int, list[float]] | None = None
_vector_cache_version: int = 0


def invalidate_vector_cache():
    """Call when embeddings are added/removed."""
    global _vector_cache
    _vector_cache = None


def search_product_vectors(
    query: list[float],
    product_vectors: dict[int, list[float]],
    top_k: int = 10,
    threshold: float = 0.0,
) -> list[tuple[int, float]]:
    """Fast cosine similarity search using numpy batch computation."""
    if not product_vectors:
        return []

    product_ids = list(product_vectors.keys())
    matrix = np.array([product_vectors[pid] for pid in product_ids], dtype=np.float32)
    query_vec = np.array(query, dtype=np.float32)

    # Batch cosine similarity
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query_vec)
    norms[norms == 0] = 1e-10  # avoid division by zero
    similarities = np.dot(matrix, query_vec) / norms

    # Filter and sort
    results = [
        (product_ids[i], float(similarities[i]))
        for i in range(len(product_ids))
        if similarities[i] >= threshold
    ]
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]
```

Update `semantic.py` `/search` endpoint to:
1. Read `semantic_search_provider` from DB settings
2. Use that provider (not request param) to embed the query
3. Load `ProductSearchVector` rows into cache dict
4. Call `search_product_vectors()` instead of iterating chunk embeddings

**Step 4: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`

**Step 5: Commit**

```bash
git add backend/grimoire/services/embeddings.py backend/grimoire/api/routes/semantic.py backend/tests/test_semantic_search.py
git commit -m "feat: fast numpy semantic search with per-product vectors"
```

---

### Task 5: Frontend — semantic API client

**Files:**
- Create: `frontend/src/api/semantic.ts`

**Step 1: Create the API client**

```typescript
import apiClient from './client';
import type { Product } from '../types/product';

export interface SemanticSearchStatus {
  enabled: boolean;
  provider: string;
  has_embeddings: boolean;
  embedded_count: number;
}

export interface SemanticSearchResult {
  product_id: number;
  title: string;
  score: number;
  matched_chunk: string;
  // Full product data for grid display
  id: number;
  file_name: string;
  cover_url?: string;
  game_system?: string;
  product_type?: string;
  publisher?: string;
  tags?: any[];
  processing_status?: any;
}

export interface SemanticSearchResponse {
  query: string;
  results: SemanticSearchResult[];
  total_matches: number;
}

export async function getSemanticSearchStatus(): Promise<SemanticSearchStatus> {
  const response = await apiClient.get<SemanticSearchStatus>('/semantic/search-status');
  return response.data;
}

export async function semanticSearch(query: string, topK: number = 20): Promise<SemanticSearchResponse> {
  const response = await apiClient.post<SemanticSearchResponse>('/semantic/search', {
    query,
    top_k: topK,
    threshold: 0.3,
  });
  return response.data;
}

export async function updateSemanticSearchProvider(provider: string): Promise<void> {
  await apiClient.patch('/settings', { semantic_search_provider: provider });
}
```

**Step 2: Commit**

```bash
git add frontend/src/api/semantic.ts
git commit -m "feat: add semantic search API client"
```

---

### Task 6: Frontend — "Semantic" toggle in Library search bar

**Files:**
- Modify: `frontend/src/pages/Library.tsx`

**Step 1: Add semantic search state and query**

Add imports:
```typescript
import { getSemanticSearchStatus, semanticSearch } from '../api/semantic';
```

Add state alongside existing `searchContent`:
```typescript
const [searchSemantic, setSearchSemantic] = useState(false);
```

Add query for search status:
```typescript
const { data: semanticStatus } = useQuery({
  queryKey: ['semantic-search-status'],
  queryFn: getSemanticSearchStatus,
  staleTime: 300000, // 5 min
});
```

Add semantic search query:
```typescript
const {
  data: semanticData,
  isLoading: semanticLoading,
  error: semanticError,
} = useQuery({
  queryKey: ['semantic-search', activeSearch],
  queryFn: () => semanticSearch(activeSearch),
  enabled: activeSearch.length > 0 && searchSemantic,
  staleTime: 60000,
});
```

**Step 2: Update toggle logic**

Make Content and Semantic mutually exclusive:
```typescript
const handleContentToggle = () => {
  setSearchContent(!searchContent);
  setSearchSemantic(false);
};

const handleSemanticToggle = () => {
  setSearchSemantic(!searchSemantic);
  setSearchContent(false);
};
```

Update `handleSearch` to handle semantic mode:
```typescript
const handleSearch = (e: React.FormEvent) => {
  e.preventDefault();
  if (searchContent || searchSemantic) {
    setActiveSearch(searchInput);
  } else {
    setFilters((prev) => ({ ...prev, search: searchInput }));
    setActiveSearch('');
  }
};
```

Update display logic:
```typescript
const isSearching = activeSearch.length > 0;
const displayProducts = isSearching
  ? (searchSemantic ? (semanticData?.results || []) : (searchData?.results || []))
  : allProducts;
const displayLoading = isSearching
  ? (searchSemantic ? semanticLoading : searchLoading)
  : isLoading;
const displayError = isSearching
  ? (searchSemantic ? semanticError : searchError)
  : error;
```

**Step 3: Add "Semantic" pill button**

Add after the "Content" button:
```tsx
<button
  onClick={handleSemanticToggle}
  disabled={!semanticStatus?.enabled}
  className="flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
  style={{
    backgroundColor: searchSemantic ? 'var(--color-accent-light)' : 'var(--color-surface-raised)',
    color: searchSemantic ? 'var(--color-accent)' : 'var(--color-text-secondary)',
    border: `1px solid ${searchSemantic ? 'var(--color-accent)' : 'var(--color-border)'}`,
  }}
  title={!semanticStatus?.enabled ? 'Configure a search provider in Settings to enable semantic search' : 'Search with AI embeddings'}
>
  Semantic
</button>
```

**Step 4: Update placeholder and result text**

```typescript
placeholder={searchSemantic ? 'Search with AI...' : searchContent ? 'Search in PDF content...' : 'Search titles...'}
```

Result count:
```tsx
{searchSemantic && ' (semantic search)'}
```

**Step 5: Update the debounced search effect**

```typescript
useEffect(() => {
  if (!searchContent && !searchSemantic) {
    setFilters(prev => ({ ...prev, search: debouncedSearch || undefined }));
  }
}, [debouncedSearch, searchContent, searchSemantic]);
```

**Step 6: Commit**

```bash
git add frontend/src/pages/Library.tsx
git commit -m "feat: add Semantic toggle to Library search bar"
```

---

### Task 7: Frontend — Search Provider dropdown in Settings page

**Files:**
- Modify: `frontend/src/pages/LibraryManagement.tsx`

**Step 1: Add provider state and mutation**

In the component, add state for the current provider setting:
```typescript
const { data: settingsData } = useQuery({
  queryKey: ['settings'],
  queryFn: async () => {
    const res = await apiClient.get('/settings');
    return res.data;
  },
});

const semanticProvider = settingsData?.semantic_search_provider || 'none';
```

Add mutation for updating:
```typescript
const updateProviderMutation = useMutation({
  mutationFn: async (provider: string) => {
    await apiClient.patch('/settings', { semantic_search_provider: provider });
  },
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['settings'] });
    queryClient.invalidateQueries({ queryKey: ['semantic-search-status'] });
  },
});
```

**Step 2: Add dropdown in the Semantic Search section**

Insert after the progress bar area (around line 1500), before the provider status section:

```tsx
<div className="mt-4 rounded-md p-4" style={{ backgroundColor: 'var(--color-surface-raised)' }}>
  <label className="block text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
    Search Provider
  </label>
  <p className="text-xs mb-2" style={{ color: 'var(--color-text-secondary)' }}>
    Choose which provider embeds your search queries. This is separate from the provider used for product identification.
  </p>
  <select
    value={semanticProvider}
    onChange={(e) => updateProviderMutation.mutate(e.target.value)}
    className="rounded-md px-3 py-2 text-sm"
    style={{
      backgroundColor: 'var(--color-bg)',
      border: '1px solid var(--color-border)',
      color: 'var(--color-text-primary)',
    }}
  >
    <option value="none">Disabled</option>
    {embeddingStats?.providers?.ollama && <option value="ollama">Ollama</option>}
    {embeddingStats?.providers?.openai && <option value="openai">OpenAI</option>}
    {embeddingStats?.providers?.local && <option value="local">Local (sentence-transformers)</option>}
  </select>
</div>
```

**Step 3: Commit**

```bash
git add frontend/src/pages/LibraryManagement.tsx
git commit -m "feat: add semantic search provider dropdown in Settings"
```

---

### Task 8: Update `/semantic/search` to use provider setting and return product data for grid

**Files:**
- Modify: `backend/grimoire/api/routes/semantic.py`

**Step 1: Update the search endpoint**

The existing `semantic_search` endpoint accepts `provider` in the request body. Change it to:
1. Read `semantic_search_provider` from DB (ignore request param)
2. Use `search_product_vectors()` instead of chunk-level search
3. Return full product data (via `product_to_response`) so the frontend `ProductGrid` can display results

```python
@router.post("/search")
async def semantic_search(
    db: DbSession,
    request: SemanticSearchRequest,
) -> dict:
    """Search products using semantic similarity with per-product vectors."""
    import json
    from grimoire.models import Setting
    from grimoire.models.product_search_vector import ProductSearchVector
    from grimoire.services.embeddings import search_product_vectors, invalidate_vector_cache
    from grimoire.api.routes.products import product_to_response
    from sqlalchemy.orm import selectinload
    from grimoire.models import ProductTag

    # Read provider from settings
    result = await db.execute(
        select(Setting).where(Setting.key == "semantic_search_provider")
    )
    setting = result.scalar_one_or_none()
    provider = json.loads(setting.value) if setting else "none"

    if provider == "none":
        raise HTTPException(status_code=400, detail="Semantic search not configured. Set a search provider in Settings.")

    # Embed the query
    try:
        query_embeddings = await generate_embeddings(
            [request.query], provider, request.model
        )
        query_vector = query_embeddings[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")

    # Load per-product vectors
    sv_result = await db.execute(select(ProductSearchVector))
    search_vectors = {sv.product_id: sv.get_vector() for sv in sv_result.scalars().all()}

    if not search_vectors:
        return {"query": request.query, "results": [], "total_matches": 0}

    # Fast numpy search
    matches = search_product_vectors(
        query_vector, search_vectors, request.top_k, request.threshold
    )

    # Fetch full product data for matched IDs
    matched_ids = [pid for pid, _ in matches]
    score_map = {pid: score for pid, score in matches}

    products_query = (
        select(Product)
        .where(Product.id.in_(matched_ids))
        .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
    )
    products_result = await db.execute(products_query)
    products = {p.id: p for p in products_result.scalars().all()}

    results = []
    for product_id in matched_ids:
        product = products.get(product_id)
        if not product:
            continue
        item = product_to_response(product).model_dump()
        item["score"] = round(score_map[product_id], 4)
        results.append(item)

    return {
        "query": request.query,
        "results": results,
        "total_matches": len(results),
    }
```

**Step 2: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`

**Step 3: Commit**

```bash
git add backend/grimoire/api/routes/semantic.py
git commit -m "feat: update semantic search to use provider setting and product vectors"
```

---

### Task 9: Invalidate vector cache when embeddings change

**Files:**
- Modify: `backend/grimoire/api/routes/semantic.py` — call `invalidate_vector_cache()` in `embed_product`, `embed_batch`, `embed_all_products`, `delete_product_embeddings`

**Step 1: Add cache invalidation calls**

In each endpoint that modifies embeddings, add after the DB commit:

```python
from grimoire.services.embeddings import invalidate_vector_cache
invalidate_vector_cache()
```

**Step 2: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`

**Step 3: Commit**

```bash
git add backend/grimoire/api/routes/semantic.py
git commit -m "feat: invalidate vector cache when embeddings change"
```

---

### Task 10: End-to-end manual testing

**Step 1: Start backend and frontend**

```bash
cd backend && python -m grimoire.main
cd frontend && npm run dev
```

**Step 2: Verify search-status endpoint**

- Visit Settings > Processing tab
- Confirm the Search Provider dropdown appears in the Semantic Search section
- Set provider to "Ollama" (or whichever is available)

**Step 3: Verify Library search bar**

- Confirm "Semantic" pill appears and is enabled (if provider set + embeddings exist)
- Search with title mode — works as before
- Toggle "Content" — works as before
- Toggle "Semantic" — enter a query like "swamp adventure" and press Enter
- Confirm results appear in the product grid
- Confirm switching between modes deactivates the other

**Step 4: Verify disabled state**

- Set provider to "Disabled" in Settings
- Confirm "Semantic" pill is greyed out with tooltip
- Confirm title and content search still work normally

**Step 5: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests pass

**Step 6: Final commit**

```bash
git commit -m "feat: integrated semantic search complete"
```
