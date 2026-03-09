# Image Gallery, Collections & Auto-Tagging Design

## Problem

Many RPG PDFs are maps and stock art — image-heavy content with minimal text. The current pipeline detects these as "needs OCR" but OCR is pointless for this content. These products need a different display and organization approach.

## Solution

Extract embedded images from image-heavy PDFs, display them in a dedicated gallery view, and support collections and tagging for organization.

## Section 1: Auto-Detection & Classification

When `detect_needs_ocr` identifies a PDF as image-heavy (low text + images):

1. **Auto-set `product_type`** using heuristics:
   - Folder/filename contains "map", "cartography", "battlemap" → `Map`
   - Folder/filename contains "stock", "art", "token", "portrait", "illustration" → `Stock Art`
   - Default for unmatched image-heavy PDFs → `Stock Art`
2. **AI refinement**: The existing AI identification step confirms or corrects the auto-tag based on cover image and extracted text.
3. **New flag**: `is_image_content: bool` on Product — marks products for image extraction instead of text/OCR extraction.

OCR is skipped entirely for these products.

## Section 2: Image Extraction Pipeline

New queue task `extract_images` (Priority 2), triggered when `is_image_content = True`.

### Process

1. Iterate each page using PyMuPDF.
2. Call `page.get_images()` to list embedded image objects.
3. Extract each image via `fitz.Pixmap()` — keep original resolution.
4. If a page has no extractable images, fall back to page rendering (`page.get_pixmap()`).
5. Save images as WebP (JPEG fallback).
6. Store metadata (page number, dimensions, original format, file size) in a JSON manifest.

### Storage

```
/backend/data/images/
  └── {product_id}/
      ├── manifest.json
      ├── 001.webp
      ├── 002.webp
      └── ...
```

### Product Model Additions

- `is_image_content: bool` — triggers image extraction instead of OCR
- `images_extracted: bool` — processing complete flag
- `image_count: int` — number of extracted images

## Section 3: Collections & Tags

### Database Tables

**`collections`**: `id`, `name`, `description`, `cover_product_id` (optional), `created_at`, `updated_at`

**`collection_products`** (many-to-many): `collection_id`, `product_id`, `added_at`, `sort_order`

**`tags`**: `id`, `name` (unique, normalized lowercase), `is_builtin: bool`

**`product_tags`** (many-to-many): `product_id`, `tag_id`

### Built-in Categories

Seeded on first run: Map, Stock Art, Token, Handout, Portrait, Scene, Item, Texture.

Cannot be deleted. Otherwise behave the same as custom tags.

### Auto-tagging

When a product is classified as Map or Stock Art (Section 1), the corresponding built-in tag is automatically applied.

## Section 4: Gallery View (Frontend)

### Route

`/gallery` — top-level page.

### Layout

**Left sidebar** — filter panel:
- Tag filter (checkboxes for built-in categories, searchable list for custom tags)
- Collection filter (dropdown or list)
- Sort options (name, date added, page count)

**Main area** — responsive image grid:
- Each card: cover image, title, tag badges, image count
- Click card → expanded view with all extracted images in a grid
- From expanded view: page through images, open in PDF viewer, add to collection, manage tags

### Collection Management

- Create/rename/delete collections from gallery sidebar
- Add products via context menu or button on product card
- Drag-and-drop reordering within collections

### Tag Management

- Add/remove tags from expanded product view
- Bulk operations: select multiple products, apply tags

### API Endpoints

- `GET /api/v1/gallery` — paginated image-content products with filtering
- `GET /api/v1/products/{id}/images` — list extracted images for a product
- `GET /api/v1/products/{id}/images/{index}` — serve a specific image
- `GET /api/v1/collections` — CRUD
- `GET /api/v1/tags` — CRUD
- `POST /api/v1/products/{id}/tags` — manage product tags
- `POST /api/v1/collections/{id}/products` — manage collection membership
