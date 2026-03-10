# Bulk Product Update Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow users to select multiple products via checkboxes and bulk-edit 10 metadata fields through a modal with preview step.

**Architecture:** Extend the existing `/api/v1/bulk/update` endpoint to support all 10 fields with explicit null support. Add checkbox selection to ProductCard, selection state in Library, a floating toolbar, and a BulkEditModal with two views (edit form + preview).

**Tech Stack:** FastAPI/Pydantic (backend), React/TypeScript with React Query (frontend), existing CSS variable theming system.

**Design doc:** `docs/plans/2026-03-10-bulk-update-design.md`

---

### Task 1: Extend Backend BulkUpdateRequest Schema

**Files:**
- Modify: `backend/grimoire/api/routes/bulk.py:28-35`
- Test: `backend/tests/test_bulk.py` (create if not exists)

**Step 1: Write the failing test**

Create `backend/tests/test_bulk.py`:

```python
"""Tests for bulk update endpoint."""
import pytest
from httpx import AsyncClient, ASGITransport
from grimoire.main import app
from grimoire.models import Product


@pytest.fixture
async def test_products(db):
    """Create test products for bulk operations."""
    products = []
    for i in range(3):
        p = Product(
            file_path=f"/test/product_{i}.pdf",
            file_name=f"product_{i}.pdf",
            file_size=1000,
            game_system="Old System",
            product_type="Adventure",
            publisher="Old Publisher",
        )
        db.add(p)
    await db.commit()
    # Re-query to get IDs
    from sqlalchemy import select
    result = await db.execute(select(Product))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_bulk_update_extended_fields(db, test_products):
    """Bulk update should support all 10 metadata fields."""
    from grimoire.api.routes.bulk import BulkUpdateRequest

    req = BulkUpdateRequest(
        product_ids=[p.id for p in test_products],
        game_system="D&D 5e",
        author="Test Author",
        genre="Fantasy",
        setting="Forgotten Realms",
        series="Lost Mine",
        estimated_runtime="one-shot",
        format="pdf",
    )
    assert req.game_system == "D&D 5e"
    assert req.author == "Test Author"
    assert req.genre == "Fantasy"
    assert req.setting == "Forgotten Realms"


@pytest.mark.asyncio
async def test_bulk_update_explicit_clear(db, test_products):
    """Bulk update should support clearing fields with empty string."""
    from grimoire.api.routes.bulk import BulkUpdateRequest

    req = BulkUpdateRequest(
        product_ids=[p.id for p in test_products],
        game_system="",  # empty string = clear the field
    )
    assert req.game_system == ""
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_bulk.py -v`
Expected: FAIL — BulkUpdateRequest doesn't accept `author`, `genre`, etc.

**Step 3: Extend BulkUpdateRequest and bulk_update_products**

In `backend/grimoire/api/routes/bulk.py`, replace the `BulkUpdateRequest` class (lines 28-35) with:

```python
# Sentinel to distinguish "not provided" from "set to None/clear"
_UNSET = object()


class BulkUpdateRequest(BaseModel):
    """Request to update fields on multiple products.

    Fields set to a string value will be applied.
    Fields set to empty string "" will clear the value (set to None).
    Fields not included in the request are left unchanged.
    """

    product_ids: list[int] = Field(..., min_length=1)
    game_system: str | None = None
    product_type: str | None = None
    publisher: str | None = None
    author: str | None = None
    genre: str | None = None
    publication_year: int | None = None
    setting: str | None = None
    series: str | None = None
    estimated_runtime: str | None = None
    format: str | None = None
```

Then update the `bulk_update_products` function (lines 177-219) to handle all fields. Use `model_fields_set` to check which fields were explicitly provided:

```python
@router.post("/update", response_model=BulkResponse)
async def bulk_update_products(db: DbSession, request: BulkUpdateRequest) -> BulkResponse:
    """Update fields on multiple products."""
    products_query = select(Product).where(Product.id.in_(request.product_ids))
    products_result = await db.execute(products_query)
    products = list(products_result.scalars().all())

    affected = 0
    filter_fields_updated = False

    # Fields that trigger filter cache invalidation
    filter_relevant = {"game_system", "product_type", "publisher", "author", "genre"}

    # All updatable string fields
    string_fields = [
        "game_system", "product_type", "publisher", "author", "genre",
        "setting", "series", "estimated_runtime", "format",
    ]

    # Only update fields that were explicitly included in the request
    provided_fields = request.model_fields_set - {"product_ids"}

    if not provided_fields:
        return BulkResponse(message="No fields to update", affected=0)

    for product in products:
        updated = False

        for field in string_fields:
            if field in provided_fields:
                value = getattr(request, field)
                # Empty string means "clear the field"
                setattr(product, field, value if value != "" else None)
                updated = True
                if field in filter_relevant:
                    filter_fields_updated = True

        if "publication_year" in provided_fields:
            product.publication_year = request.publication_year
            updated = True

        if updated:
            affected += 1

    await db.commit()

    # Invalidate filter cache if filter-relevant fields were updated
    if filter_fields_updated:
        from grimoire.services.cache_service import get_cache_service
        cache = await get_cache_service()
        await cache.invalidate_filter_options()

    return BulkResponse(
        message=f"Updated products",
        affected=affected,
    )
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_bulk.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/grimoire/api/routes/bulk.py backend/tests/test_bulk.py
git commit -m "feat: extend bulk update to support all 10 metadata fields"
```

---

### Task 2: Add Bulk Update API Function to Frontend

**Files:**
- Modify: `frontend/src/api/products.ts`

**Step 1: Add the bulk update types and function**

Add to end of `frontend/src/api/products.ts`:

```typescript
export interface BulkUpdateFields {
  game_system?: string | null;
  product_type?: string | null;
  genre?: string | null;
  publisher?: string | null;
  author?: string | null;
  publication_year?: number | null;
  setting?: string | null;
  series?: string | null;
  estimated_runtime?: string | null;
  format?: string | null;
}

export interface BulkUpdateRequest {
  product_ids: number[];
  // fields from BulkUpdateFields spread in
  [key: string]: unknown;
}

export interface BulkResponse {
  message: string;
  affected: number;
  errors: string[];
}

export async function bulkUpdateProducts(
  productIds: number[],
  fields: BulkUpdateFields,
): Promise<BulkResponse> {
  const response = await api.post<BulkResponse>('/bulk/update', {
    product_ids: productIds,
    ...fields,
  });
  return response.data;
}
```

**Step 2: Commit**

```bash
git add frontend/src/api/products.ts
git commit -m "feat: add bulk update API client function"
```

---

### Task 3: Add Checkbox Selection to ProductCard

**Files:**
- Modify: `frontend/src/components/ProductCard.tsx`

**Step 1: Add selection props and checkbox**

Update the `ProductCardProps` interface and component to accept selection state:

```typescript
interface ProductCardProps {
  product: Product;
  onClick?: (product: Product) => void;
  viewMode?: 'grid' | 'list';
  selectable?: boolean;
  selected?: boolean;
  onSelectionChange?: (productId: number, selected: boolean) => void;
}
```

Add a checkbox to both grid and list views. For **grid view**, position it absolute top-left with opacity-0 on idle, opacity-100 on hover or when selected. For **list view**, show it always as the first element in the flex row.

The checkbox should:
- Call `onSelectionChange(product.id, !selected)` on click
- `e.stopPropagation()` to prevent triggering the card's onClick
- Use `var(--color-accent)` for checked state styling

**Grid view checkbox** (inside the grid `<article>`, as first child of the cover div):

```tsx
{selectable && (
  <div
    className={`absolute top-2 left-2 z-10 transition-opacity ${selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
  >
    <input
      type="checkbox"
      checked={selected}
      onChange={(e) => {
        e.stopPropagation();
        onSelectionChange?.(product.id, e.target.checked);
      }}
      onClick={(e) => e.stopPropagation()}
      className="h-5 w-5 rounded cursor-pointer accent-[var(--color-accent)]"
    />
  </div>
)}
```

**List view checkbox** (first element in the flex row, before the cover image div):

```tsx
{selectable && (
  <div className="flex-shrink-0">
    <input
      type="checkbox"
      checked={selected}
      onChange={(e) => {
        e.stopPropagation();
        onSelectionChange?.(product.id, e.target.checked);
      }}
      onClick={(e) => e.stopPropagation()}
      className="h-5 w-5 rounded cursor-pointer accent-[var(--color-accent)]"
    />
  </div>
)}
```

**Step 2: Commit**

```bash
git add frontend/src/components/ProductCard.tsx
git commit -m "feat: add checkbox selection to ProductCard"
```

---

### Task 4: Pass Selection State Through ProductGrid

**Files:**
- Modify: `frontend/src/components/ProductGrid.tsx`

**Step 1: Add selection props to ProductGrid**

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
}
```

Pass these through to each `ProductCard`:

```tsx
<ProductCard
  key={product.id}
  product={product}
  onClick={onProductClick}
  viewMode={viewMode}
  selectable={selectable}
  selected={selectedIds?.has(product.id)}
  onSelectionChange={onSelectionChange}
/>
```

**Step 2: Commit**

```bash
git add frontend/src/components/ProductGrid.tsx
git commit -m "feat: pass selection state through ProductGrid"
```

---

### Task 5: Add Selection State and Floating Toolbar to Library

**Files:**
- Modify: `frontend/src/pages/Library.tsx`

**Step 1: Add selection state management**

Add to Library component state:

```typescript
const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
const [showBulkEdit, setShowBulkEdit] = useState(false);

const handleSelectionChange = useCallback((productId: number, selected: boolean) => {
  setSelectedIds(prev => {
    const next = new Set(prev);
    if (selected) {
      next.add(productId);
    } else {
      next.delete(productId);
    }
    return next;
  });
}, []);

const handleSelectAll = useCallback(() => {
  if (selectedIds.size === displayProducts.length) {
    setSelectedIds(new Set());
  } else {
    setSelectedIds(new Set(displayProducts.map(p => p.id)));
  }
}, [displayProducts, selectedIds.size]);

const clearSelection = useCallback(() => {
  setSelectedIds(new Set());
}, []);
```

**Step 2: Pass selection props to ProductGrid**

Update the `<ProductGrid>` in the JSX:

```tsx
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
/>
```

**Step 3: Add Select All checkbox to the product count bar**

In the `<div className="mb-4 flex items-center justify-between">` area (around line 266), add a select-all checkbox:

```tsx
<div className="mb-4 flex items-center justify-between">
  <div className="flex items-center gap-3">
    <input
      type="checkbox"
      checked={displayProducts.length > 0 && selectedIds.size === displayProducts.length}
      ref={(el) => {
        if (el) el.indeterminate = selectedIds.size > 0 && selectedIds.size < displayProducts.length;
      }}
      onChange={handleSelectAll}
      className="h-5 w-5 rounded cursor-pointer accent-[var(--color-accent)]"
      title="Select all"
    />
    <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
      {/* existing count text */}
    </p>
  </div>
  {/* existing clear search button */}
</div>
```

**Step 4: Add Floating Toolbar**

Add this just before the closing `</div>` of the Library component (before the ProductDetail modal):

```tsx
{/* Floating bulk action toolbar */}
{selectedIds.size > 0 && (
  <div
    className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-4 rounded-lg px-6 py-3 shadow-xl"
    style={{
      backgroundColor: 'var(--color-surface)',
      border: '1px solid var(--color-border)',
    }}
  >
    <span className="text-base font-medium" style={{ color: 'var(--color-text-primary)' }}>
      {selectedIds.size} selected
    </span>
    <button
      onClick={() => setShowBulkEdit(true)}
      className="rounded-md px-4 py-2 text-sm font-medium text-white"
      style={{ backgroundColor: 'var(--color-accent)' }}
    >
      Edit Selected
    </button>
    <button
      onClick={clearSelection}
      className="rounded-md px-4 py-2 text-sm font-medium"
      style={{
        color: 'var(--color-text-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      Clear
    </button>
  </div>
)}
```

**Step 5: Commit**

```bash
git add frontend/src/pages/Library.tsx
git commit -m "feat: add product selection state and floating toolbar"
```

---

### Task 6: Create BulkEditModal Component

**Files:**
- Create: `frontend/src/components/BulkEditModal.tsx`

**Step 1: Create the modal component**

This is the largest piece. The modal has two views:
1. **Edit form** — two-column grid of 10 fields, each with a "clear" toggle
2. **Preview** — summary of changes + list of affected product titles

```typescript
// frontend/src/components/BulkEditModal.tsx
import { useState, useCallback } from 'react';
import { X } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { bulkUpdateProducts, type BulkUpdateFields } from '../api/products';
import type { Product } from '../types/product';

interface BulkEditModalProps {
  selectedProducts: Product[];
  onClose: () => void;
  onComplete: () => void;
}

interface FieldState {
  value: string;
  touched: boolean;  // user has interacted with this field
  clear: boolean;    // explicitly clear (set to null)
}

const FIELD_LABELS: Record<string, string> = {
  game_system: 'Game System',
  product_type: 'Product Type',
  genre: 'Genre',
  publisher: 'Publisher',
  author: 'Author',
  publication_year: 'Publication Year',
  setting: 'Setting',
  series: 'Series',
  estimated_runtime: 'Estimated Runtime',
  format: 'Format',
};

const LEFT_FIELDS = ['game_system', 'product_type', 'genre', 'publisher', 'author'];
const RIGHT_FIELDS = ['publication_year', 'setting', 'series', 'estimated_runtime', 'format'];

function createInitialState(): Record<string, FieldState> {
  const state: Record<string, FieldState> = {};
  for (const key of [...LEFT_FIELDS, ...RIGHT_FIELDS]) {
    state[key] = { value: '', touched: false, clear: false };
  }
  return state;
}
```

The component should:

**Edit view:**
- Render each field as a text input (number input for publication_year) with a "Clear" checkbox next to it
- When "Clear" is checked, disable the text input and mark the field for clearing
- A field is "changed" if `touched && (value !== '' || clear)`
- "Preview Changes" button enabled only when at least one field is changed
- "Cancel" button calls `onClose`

**Preview view:**
- List each change: "Set {label} to '{value}'" or "Clear {label}"
- Show "Apply to {count} products"
- Scrollable list of product titles (max-height ~200px)
- "Back" button returns to edit view
- "Apply Changes" button calls `bulkUpdateProducts` mutation
- On success: invalidate product queries, call `onComplete`, call `onClose`
- On error: show error message

**Mutation:**
```typescript
const queryClient = useQueryClient();
const mutation = useMutation({
  mutationFn: () => {
    const fields: BulkUpdateFields = {};
    for (const [key, state] of Object.entries(fieldStates)) {
      if (!state.touched) continue;
      if (state.clear) {
        if (key === 'publication_year') {
          fields[key as keyof BulkUpdateFields] = null as any;
        } else {
          (fields as any)[key] = '';  // empty string = clear
        }
      } else if (state.value !== '') {
        if (key === 'publication_year') {
          (fields as any)[key] = parseInt(state.value, 10);
        } else {
          (fields as any)[key] = state.value;
        }
      }
    }
    return bulkUpdateProducts(
      selectedProducts.map(p => p.id),
      fields,
    );
  },
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['products'] });
    queryClient.invalidateQueries({ queryKey: ['filters'] });
    onComplete();
    onClose();
  },
});
```

**Modal overlay:** use `fixed inset-0 z-50` with semi-transparent backdrop. Modal centered, max-w-2xl, max-h-[80vh] with overflow-y-auto.

**Step 2: Commit**

```bash
git add frontend/src/components/BulkEditModal.tsx
git commit -m "feat: create BulkEditModal component with edit and preview views"
```

---

### Task 7: Wire BulkEditModal into Library

**Files:**
- Modify: `frontend/src/pages/Library.tsx`

**Step 1: Import and render BulkEditModal**

Add import:
```typescript
import { BulkEditModal } from '../components/BulkEditModal';
```

Add the modal render (after the floating toolbar, before ProductDetail):

```tsx
{showBulkEdit && (
  <BulkEditModal
    selectedProducts={displayProducts.filter(p => selectedIds.has(p.id))}
    onClose={() => setShowBulkEdit(false)}
    onComplete={clearSelection}
  />
)}
```

**Step 2: Commit**

```bash
git add frontend/src/pages/Library.tsx
git commit -m "feat: wire BulkEditModal into Library page"
```

---

### Task 8: Manual Testing & Polish

**Step 1: Start the backend**

```bash
cd backend && python -m pytest tests/ -v  # verify all tests pass
```

**Step 2: Start the frontend dev server and test manually**

Test the full flow:
1. Load Library page — checkboxes appear on hover (grid) / always (list)
2. Select a few products — floating toolbar appears with count
3. Click "Edit Selected" — modal opens with 10 fields
4. Fill in some fields, toggle "Clear" on others
5. Click "Preview Changes" — see summary and product list
6. Click "Apply Changes" — products update, modal closes, selection clears
7. Verify the updated values appear on the product cards

**Step 3: Commit any polish fixes**

```bash
git add -A
git commit -m "fix: bulk edit polish and fixes"
```
