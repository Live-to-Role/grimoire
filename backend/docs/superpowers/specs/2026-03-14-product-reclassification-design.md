# Product Reclassification Design

**Date:** 2026-03-14
**Status:** Draft

## Problem

Many PDFs in the library are maps or stock art but weren't identified as image content by the classifier. The filename pattern matcher misses files like `1-Lower_Main_Level.pdf` (no "map" keyword), and the content analysis threshold (90% for unmatched files) is intentionally strict. Users need a way to manually reclassify these products and trigger image extraction.

## Solution

Extend the existing BulkEditModal with two new fields that allow reclassification in both directions (regular product ↔ image content). When reclassifying to image content, the system auto-tags and queues image extraction. When reclassifying back to regular product, extracted images are deleted.

## Design

### Frontend: BulkEditModal Changes

**Two new fields added to the existing field grid:**

1. **"Image Content" toggle** — three-state control:
   - Unchanged (default) — field not touched, no effect
   - Yes — marks selected products as image content
   - No — marks selected products as regular (non-image) products

2. **"Content Type" dropdown** — appears only when Image Content is set to "Yes":
   - Options: Map, Stock Art, Token, Handout, Portrait, Scene, Item, Texture
   - These match the 8 built-in tags from `tag_service.BUILTIN_TAGS`
   - Required when Image Content is "Yes"

**Field placement:** Add these as a full-width section above the existing two-column field grid, visually separated. The toggle + dropdown sit on one row.

**Field interaction:** When Image Content is set to "Yes", the existing `product_type` field is disabled (content_type overrides it). When set to "No" or "Unchanged", `product_type` remains editable as normal.

**Preview step additions:**
- Shows reclassification direction and count (e.g., "3 products → Image Content (Map)")
- If any selected products already have `images_extracted=True` and are being set to image content, shows: "X products already have extracted images. Re-extract?" with a checkbox (default unchecked)
- If reclassifying to regular product, shows: "Extracted images will be deleted for X products"

**Query invalidation:** On success, invalidate `['products']`, `['filters']`, and `['gallery']` query keys.

### Backend: Bulk Update Endpoint Changes

**Extended `BulkUpdateRequest` schema** (`bulk.py`):
```python
# New fields
is_image_content: bool | None = None      # True = image content, False = regular
content_type: str | None = None           # One of the 8 built-in tag names
re_extract: bool = False                  # Re-extract images for already-extracted products
```

**Validation (Pydantic `model_validator`):**
- If `is_image_content=True`, `content_type` must be provided and must match a built-in tag name
- If `is_image_content=True` and `product_type` is also explicitly set, `product_type` is ignored (content_type wins)
- If `is_image_content=False`, `content_type` is ignored

**When `is_image_content=True`:**
1. Remove any existing auto-tagged content_type tags (ProductTag where `source="auto"` and tag is a built-in content_type tag) — prevents stale tags when changing type
2. Set `product.is_image_content = True`
3. Set `product.product_type` to the content_type value
4. Auto-tag: find the built-in Tag matching content_type name, create ProductTag with `source="auto"` (skip if already tagged with that exact tag)
5. Queue `extract_images` task (priority=2) for each product where:
   - `images_extracted` is False, OR
   - `re_extract` is True
   - Duplicate check: `SELECT 1 FROM processing_queue WHERE product_id = ? AND task_type = 'extract_images' AND status IN ('pending', 'processing')` — skip if found

**When `is_image_content=False`:**
1. Set `product.is_image_content = False`
2. Set `product.product_type = None` (clear it for consistency)
3. Set `product.images_extracted = False`
4. Set `product.image_count = None`
5. Remove auto-tagged content_type tags (ProductTag where `source="auto"` and tag is a built-in content_type tag)
6. Commit database changes first, then delete extracted images directory: `settings.data_dir / "images" / {product.id}`. If file deletion fails, log a warning but do not roll back — the DB state is authoritative.

**Note on tag source:** Reclassification tags use `source="auto"` (not `"bulk"`) because the cleanup logic in the `is_image_content=False` flow filters on `source="auto"` to identify content-type tags. User-applied tags via bulk tagging use `source="bulk"` and are not affected by reclassification.

**Response:** Existing `BulkResponse` format. Include extraction queue count in message (e.g., "Updated 5 products. Queued 3 for image extraction.").

### Frontend: API Client Changes

**Extended `BulkUpdateFields`** (`products.ts`):
```typescript
export interface BulkUpdateFields {
  // ... existing fields ...
  is_image_content?: boolean;
  content_type?: string;
  re_extract?: boolean;
}
```

The frontend omits `is_image_content` from the request when the toggle is "Unchanged" (field not touched). The backend uses `model_fields_set` to detect this.

No other API client changes needed — the existing `bulkUpdateProducts` function spreads fields into the request.

### Data Flow

```
Select products in Library → Click "Edit Selected" →
Toggle "Image Content: Yes" → Pick "Map" from dropdown →
Click "Preview Changes" →
See: "5 products → Image Content (Map), 2 already extracted (re-extract?)" →
Click "Apply Changes" →
Backend: update fields, create tags, commit, queue extraction →
Queue processor: extract images in background →
Products appear in Gallery view
```

### Edge Cases

- **Already image content, setting to image content with different type:** Removes old auto-tag, updates product_type and adds new auto-tag, optionally re-extracts
- **Already regular, setting to regular:** No-op for image fields; other bulk edit fields still apply
- **Mixed selection (some image, some regular):** All get the same treatment based on the toggle
- **Extraction fails:** Existing queue error handling applies; product stays with `images_extracted=False`
- **Concurrent extraction:** Duplicate check query prevents queueing if a pending/processing task exists for the same product
- **File deletion failure:** Logged as warning; DB state is authoritative and already committed

## Files to Modify

### Backend
- `backend/grimoire/api/routes/bulk.py` — extend request schema (with model_validator) and update handler
- `backend/grimoire/services/tag_service.py` — add helper to auto-tag/remove-tag by content type

### Frontend
- `frontend/src/components/BulkEditModal.tsx` — add Image Content toggle + Content Type dropdown + preview logic + gallery query invalidation
- `frontend/src/api/products.ts` — extend BulkUpdateFields interface

### Tests
- `backend/tests/api/test_bulk_reclassify.py` — new test file for reclassification scenarios
