# Collections & Tags Implementation Plan

**Status: ✅ COMPLETED**

---

## Current State Analysis

### Backend (✅ Complete)
- **Models**: `Collection`, `CollectionProduct`, `Tag`, `ProductTag` fully defined
- **Schemas**: Full CRUD schemas for validation
- **API Routes**: 
  - `/collections` - CRUD + add/remove products
  - `/tags` - CRUD operations
- **Products API**: Supports filtering by `collection` and `tags` parameters

### Frontend (⚠️ Partial)
- **Sidebar**: Displays collections/tags from API, handles selection for filtering
- **Library**: Accepts `selectedCollection`/`selectedTag` props for filtering
- **ProductDetail**: Can display existing tags on products (read-only)

## What's Missing

| Feature | Status |
|---------|--------|
| UI to **create** collections | ❌ Missing |
| UI to **create** tags | ❌ Missing |
| UI to **add products to collections** | ❌ Missing |
| UI to **add tags to products** | ❌ Missing |
| UI to **manage/edit/delete** collections | ❌ Missing |
| UI to **manage/edit/delete** tags | ❌ Missing |
| Frontend API client functions | ❌ Missing |

---

## Implementation Plan

### Phase 1: API Client Functions
**Files**: `frontend/src/api/collections.ts`, `frontend/src/api/tags.ts`

```typescript
// collections.ts
- getCollections()
- getCollection(id)
- createCollection(data: { name, description?, color?, icon? })
- updateCollection(id, data)
- deleteCollection(id)
- addProductToCollection(collectionId, productId)
- removeProductFromCollection(collectionId, productId)

// tags.ts
- getTags(category?)
- getTag(id)
- createTag(data: { name, category?, color? })
- updateTag(id, data)
- deleteTag(id)
- addTagToProduct(productId, tagId)
- removeTagFromProduct(productId, tagId)
```

### Phase 2: Management Modals
**Files**: `frontend/src/components/CollectionManager.tsx`, `frontend/src/components/TagManager.tsx`

#### CollectionManager
- Modal form with fields: name (required), description, color picker, icon selector
- Create/Edit modes based on whether collection prop is passed
- Delete confirmation dialog

#### TagManager
- Modal form with fields: name (required), category dropdown, color picker
- Create/Edit modes
- Delete confirmation dialog

### Phase 3: Sidebar Enhancements
**File**: `frontend/src/components/Sidebar.tsx`

- Add `+` button next to "COLLECTIONS" header → opens CollectionManager in create mode
- Add `+` button next to "TAGS" header → opens TagManager in create mode
- Add hover action buttons (edit/delete) on each collection/tag item
- Or: Add right-click context menu with Edit/Delete options

### Phase 4: ProductDetail Enhancements
**File**: `frontend/src/components/ProductDetail.tsx`

#### Add to Collection
- Add dropdown button similar to existing "Add to Campaign" functionality
- Shows list of collections with checkmarks for current memberships
- Click to toggle membership

#### Manage Tags
- Add tag picker section in the Details tab
- Shows current tags with X buttons to remove
- Autocomplete input to search and add existing tags
- Option to create new tag inline

---

## Backend API Reference

### Collections Endpoints
```
GET    /api/v1/collections                    - List all collections
POST   /api/v1/collections                    - Create collection
GET    /api/v1/collections/{id}               - Get collection with products
PATCH  /api/v1/collections/{id}               - Update collection
DELETE /api/v1/collections/{id}               - Delete collection
POST   /api/v1/collections/{id}/products      - Add product to collection
DELETE /api/v1/collections/{id}/products/{pid} - Remove product from collection
```

### Tags Endpoints
```
GET    /api/v1/tags                           - List all tags
POST   /api/v1/tags                           - Create tag
GET    /api/v1/tags/{id}                      - Get tag
PATCH  /api/v1/tags/{id}                      - Update tag
DELETE /api/v1/tags/{id}                      - Delete tag
```

### Product Tag Endpoints (need to verify/add)
```
POST   /api/v1/products/{id}/tags             - Add tag to product
DELETE /api/v1/products/{id}/tags/{tag_id}    - Remove tag from product
```

---

## UI/UX Considerations

1. **Color Picker**: Use a simple preset palette (8-12 colors) rather than full color picker
2. **Icons**: For collections, use Lucide icon names stored as strings
3. **Inline Creation**: Allow creating new tags directly from ProductDetail without opening modal
4. **Confirmation**: Always confirm before deleting collections/tags
5. **Accessibility**: Ensure all modals have proper focus trapping and ARIA labels
