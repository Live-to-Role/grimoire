# Image Gallery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract embedded images from map/stock art PDFs, display them in a gallery view, and support collections and tagging for organization.

**Architecture:** Extend the existing queue processor with an `extract_images` task that uses PyMuPDF to pull embedded images from PDFs detected as image-heavy. Add `is_builtin` flag to existing Tag model. Add a new `/gallery` frontend view with filtering by tags and collections.

**Tech Stack:** PyMuPDF (fitz), FastAPI, SQLAlchemy 2.x async, React 18, TypeScript, React Query v5

**Branch:** `feat/image-gallery`

## Progress

- [x] Task 1: Add `is_image_content` fields to Product model
- [x] Task 2: Add `is_builtin` field to Tag model and seed built-in tags
- [x] Task 3: Create image extractor service
- [x] Task 4: Add image classification heuristics and queue handler
- [x] Task 5: Add image serving API routes
- [x] Task 6: Add gallery API endpoint
- [x] Task 7: Create frontend gallery API client
- [x] Task 8: Create Gallery page component
- [x] Task 9: Update frontend Tag API types for `is_builtin`
- [x] Task 10: End-to-end verification

### Implementation Notes
- Task 1: Test uses `not p.is_image_content` (falsy) instead of `is False` because SQLAlchemy `default=False` is DDL-level, not Python constructor-level.
- Task 2: `test_cannot_delete_builtin_tag` queries for existing "Map" tag from seed test (session-scoped DB), avoids duplicate insert.
- Task 3: Extended existing `image_extractor.py` with new `extract_images()` function rather than replacing it. Changed top-level imports to conditional (`PYMUPDF_AVAILABLE`, `PIL_AVAILABLE`).

---

### Task 1: Add `is_image_content` fields to Product model

**Files:**
- Modify: `backend/grimoire/models/product.py:88-92` (processing status section)

**Step 1: Write the failing test**

Create `backend/tests/test_image_content_fields.py`:

```python
"""Tests for image content fields on Product model."""
import pytest
from grimoire.models import Product


def test_product_has_image_content_fields():
    """Product model should have is_image_content, images_extracted, image_count."""
    p = Product(
        file_path="/test.pdf",
        file_name="test.pdf",
        file_size=1000,
        file_hash="abc123",
    )
    assert p.is_image_content is False
    assert p.images_extracted is False
    assert p.image_count is None
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_image_content_fields.py -v`
Expected: FAIL - `is_image_content` attribute does not exist

**Step 3: Add fields to Product model**

In `backend/grimoire/models/product.py`, add after line 92 (`ai_identified`):

```python
    # Image content (maps, stock art)
    is_image_content: Mapped[bool] = mapped_column(Boolean, default=False)
    images_extracted: Mapped[bool] = mapped_column(Boolean, default=False)
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_image_content_fields.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/grimoire/models/product.py backend/tests/test_image_content_fields.py
git commit -m "feat: add is_image_content, images_extracted, image_count to Product model"
```

---

### Task 2: Add `is_builtin` field to Tag model and seed built-in tags

**Files:**
- Modify: `backend/grimoire/models/tag.py:20-23`
- Modify: `backend/grimoire/database.py:108-118` (init_db)
- Modify: `backend/grimoire/api/routes/tags.py:134-147` (delete endpoint)
- Modify: `backend/grimoire/schemas/tag.py`

**Step 1: Write the failing test**

Add to `backend/tests/test_image_content_fields.py`:

```python
from grimoire.models import Tag


def test_tag_has_is_builtin_field():
    """Tag model should have is_builtin flag."""
    tag = Tag(name="Map")
    assert tag.is_builtin is False


@pytest.mark.asyncio
async def test_seed_builtin_tags(db):
    """Seeding should create built-in tags."""
    from grimoire.services.tag_service import seed_builtin_tags
    await seed_builtin_tags(db)

    from sqlalchemy import select
    result = await db.execute(select(Tag).where(Tag.is_builtin == True))
    tags = result.scalars().all()
    names = {t.name for t in tags}
    assert "Map" in names
    assert "Stock Art" in names
    assert len(tags) == 8


@pytest.mark.asyncio
async def test_cannot_delete_builtin_tag(db):
    """Built-in tags should not be deletable via API."""
    tag = Tag(name="Map", is_builtin=True, category="content_type")
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    # The route handler checks is_builtin - tested via route test or unit
    assert tag.is_builtin is True
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_image_content_fields.py -v`
Expected: FAIL - `is_builtin` attribute does not exist

**Step 3: Add `is_builtin` to Tag model**

In `backend/grimoire/models/tag.py`, add after `color` field (line 23):

```python
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
```

Add `Boolean` to the sqlalchemy imports on line 6.

**Step 4: Create `backend/grimoire/services/tag_service.py`**

```python
"""Tag service - seeding and management of built-in tags."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Tag

BUILTIN_TAGS = [
    {"name": "Map", "category": "content_type", "color": "#4A90D9"},
    {"name": "Stock Art", "category": "content_type", "color": "#D94A8C"},
    {"name": "Token", "category": "content_type", "color": "#D9A84A"},
    {"name": "Handout", "category": "content_type", "color": "#4AD99B"},
    {"name": "Portrait", "category": "content_type", "color": "#9B4AD9"},
    {"name": "Scene", "category": "content_type", "color": "#D96A4A"},
    {"name": "Item", "category": "content_type", "color": "#4AD9D9"},
    {"name": "Texture", "category": "content_type", "color": "#8CD94A"},
]


async def seed_builtin_tags(db: AsyncSession) -> None:
    """Create built-in tags if they don't exist."""
    for tag_data in BUILTIN_TAGS:
        result = await db.execute(select(Tag).where(Tag.name == tag_data["name"]))
        existing = result.scalar_one_or_none()
        if not existing:
            tag = Tag(is_builtin=True, **tag_data)
            db.add(tag)
    await db.commit()
```

**Step 5: Call seed from `init_db`**

In `backend/grimoire/database.py`, add after exclusion rules seeding (line 117):

```python
    # Seed built-in tags
    from grimoire.services.tag_service import seed_builtin_tags
    async with async_session_maker() as session:
        await seed_builtin_tags(session)
```

**Step 6: Protect built-in tags from deletion**

In `backend/grimoire/api/routes/tags.py`, update `delete_tag` to check `is_builtin`:

```python
@router.delete("/{tag_id}", status_code=204)
async def delete_tag(db: DbSession, tag_id: int) -> Response:
    """Delete a tag."""
    query = select(Tag).where(Tag.id == tag_id)
    result = await db.execute(query)
    tag = result.scalar_one_or_none()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    if tag.is_builtin:
        raise HTTPException(status_code=403, detail="Cannot delete built-in tag")

    await db.delete(tag)
    await db.commit()

    return Response(status_code=204)
```

**Step 7: Add `is_builtin` to tag schemas**

In `backend/grimoire/schemas/tag.py`, add to `TagResponse`:

```python
class TagResponse(TagBase):
    """Schema for tag response."""
    id: int
    is_builtin: bool = False
    created_at: datetime
    product_count: int = 0

    class Config:
        from_attributes = True
```

**Step 8: Run tests**

Run: `cd backend && python -m pytest tests/test_image_content_fields.py -v`
Expected: PASS

**Step 9: Commit**

```bash
git add backend/grimoire/models/tag.py backend/grimoire/services/tag_service.py \
  backend/grimoire/database.py backend/grimoire/api/routes/tags.py \
  backend/grimoire/schemas/tag.py backend/tests/test_image_content_fields.py
git commit -m "feat: add is_builtin flag to tags and seed built-in content type tags"
```

---

### Task 3: Create image extractor service

**Files:**
- Create: `backend/grimoire/processors/image_extractor.py`
- Create: `backend/tests/test_image_extractor.py`

**Step 1: Write the failing test**

Create `backend/tests/test_image_extractor.py`:

```python
"""Tests for image extraction from PDFs."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_extract_images_creates_output_dir(tmp_path):
    """extract_images should create the output directory."""
    from grimoire.processors.image_extractor import extract_images

    # Create a minimal mock since we can't easily create a real PDF in tests
    output_dir = tmp_path / "images" / "1"
    assert not output_dir.exists()

    # We'll test with a mock PDF
    with patch("grimoire.processors.image_extractor.fitz") as mock_fitz:
        mock_doc = MagicMock()
        mock_doc.__len__ = lambda self: 0
        mock_doc.__iter__ = lambda self: iter([])
        mock_fitz.open.return_value = mock_doc

        result = extract_images(Path("/fake.pdf"), output_dir)

    assert output_dir.exists()
    assert result["image_count"] == 0
    assert (output_dir / "manifest.json").exists()


def test_extract_images_manifest_format(tmp_path):
    """Manifest should contain expected fields."""
    from grimoire.processors.image_extractor import extract_images

    output_dir = tmp_path / "images" / "1"

    with patch("grimoire.processors.image_extractor.fitz") as mock_fitz:
        mock_doc = MagicMock()
        mock_doc.__len__ = lambda self: 0
        mock_doc.__iter__ = lambda self: iter([])
        mock_fitz.open.return_value = mock_doc

        extract_images(Path("/fake.pdf"), output_dir)

    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert "images" in manifest
    assert "image_count" in manifest
    assert "total_pages" in manifest
    assert isinstance(manifest["images"], list)
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_image_extractor.py -v`
Expected: FAIL - module not found

**Step 3: Implement image extractor**

Create `backend/grimoire/processors/image_extractor.py`:

```python
"""Extract embedded images from PDFs using PyMuPDF."""

import json
import logging
from io import BytesIO
from pathlib import Path

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)


def extract_images(pdf_path: Path, output_dir: Path) -> dict:
    """
    Extract embedded images from a PDF file.

    For each page, attempts to extract embedded image objects directly.
    Falls back to page rendering if no extractable images are found on a page.

    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to save extracted images

    Returns:
        Dict with image_count, total_pages, and images list
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if not PYMUPDF_AVAILABLE:
        logger.error("PyMuPDF not available for image extraction")
        manifest = {"images": [], "image_count": 0, "total_pages": 0}
        _write_manifest(output_dir, manifest)
        return manifest

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    images = []
    image_index = 0

    for page_num, page in enumerate(doc):
        page_images = page.get_images(full=True)

        if page_images:
            # Extract embedded images directly
            for img_info in page_images:
                xref = img_info[0]
                try:
                    extracted = _extract_image_by_xref(doc, xref, output_dir, image_index)
                    if extracted:
                        extracted["page"] = page_num + 1
                        images.append(extracted)
                        image_index += 1
                except Exception as e:
                    logger.warning(f"Failed to extract image xref {xref} from page {page_num + 1}: {e}")
        else:
            # Fallback: render the page as an image
            extracted = _render_page(page, output_dir, image_index, page_num)
            if extracted:
                images.append(extracted)
                image_index += 1

    doc.close()

    manifest = {
        "images": images,
        "image_count": len(images),
        "total_pages": total_pages,
    }
    _write_manifest(output_dir, manifest)
    return manifest


def _extract_image_by_xref(doc, xref: int, output_dir: Path, index: int) -> dict | None:
    """Extract a single image by its xref and save as WebP."""
    base_image = doc.extract_image(xref)
    if not base_image or not base_image.get("image"):
        return None

    image_bytes = base_image["image"]
    width = base_image.get("width", 0)
    height = base_image.get("height", 0)
    original_ext = base_image.get("ext", "png")

    filename = f"{index + 1:03d}.webp"
    output_path = output_dir / filename

    if PIL_AVAILABLE:
        try:
            img = Image.open(BytesIO(image_bytes))
            img.save(str(output_path), "WEBP", quality=85)
        except Exception:
            # Fallback: save as original format
            filename = f"{index + 1:03d}.{original_ext}"
            output_path = output_dir / filename
            output_path.write_bytes(image_bytes)
    else:
        # No PIL — save raw bytes in original format
        filename = f"{index + 1:03d}.{original_ext}"
        output_path = output_dir / filename
        output_path.write_bytes(image_bytes)

    return {
        "filename": filename,
        "width": width,
        "height": height,
        "original_format": original_ext,
        "file_size": output_path.stat().st_size,
    }


def _render_page(page, output_dir: Path, index: int, page_num: int) -> dict | None:
    """Render a page as an image (fallback when no embedded images found)."""
    try:
        # 2x zoom for quality
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        filename = f"{index + 1:03d}.webp"
        output_path = output_dir / filename

        if PIL_AVAILABLE:
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img.save(str(output_path), "WEBP", quality=85)
        else:
            # Fallback to PNG
            filename = f"{index + 1:03d}.png"
            output_path = output_dir / filename
            pix.save(str(output_path))

        return {
            "filename": filename,
            "page": page_num + 1,
            "width": pix.width,
            "height": pix.height,
            "original_format": "rendered",
            "file_size": output_path.stat().st_size,
        }
    except Exception as e:
        logger.warning(f"Failed to render page {page_num + 1}: {e}")
        return None


def _write_manifest(output_dir: Path, manifest: dict) -> None:
    """Write the image manifest JSON file."""
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
```

**Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_image_extractor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/grimoire/processors/image_extractor.py backend/tests/test_image_extractor.py
git commit -m "feat: add image extractor service for maps and stock art PDFs"
```

---

### Task 4: Add image classification heuristics and queue handler

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py:109-148` (handle_text_task)
- Create: `backend/grimoire/processors/image_classifier.py`

**Step 1: Write the failing test**

Create `backend/tests/test_image_classifier.py`:

```python
"""Tests for image content classification heuristics."""
import pytest


def test_classify_map_by_filename():
    from grimoire.processors.image_classifier import classify_image_content
    result = classify_image_content("Dungeon Battlemap Pack.pdf", "/maps/battlemap.pdf")
    assert result == "Map"


def test_classify_stock_art_by_filename():
    from grimoire.processors.image_classifier import classify_image_content
    result = classify_image_content("Fantasy Stock Art Collection.pdf", "/art/stock.pdf")
    assert result == "Stock Art"


def test_classify_map_by_folder():
    from grimoire.processors.image_classifier import classify_image_content
    result = classify_image_content("pack_01.pdf", "/rpg/Maps/Caves/pack_01.pdf")
    assert result == "Map"


def test_classify_default_to_stock_art():
    from grimoire.processors.image_classifier import classify_image_content
    result = classify_image_content("unknown_images.pdf", "/rpg/misc/unknown_images.pdf")
    assert result == "Stock Art"


def test_classify_token_by_filename():
    from grimoire.processors.image_classifier import classify_image_content
    result = classify_image_content("NPC Token Pack.pdf", "/tokens/npc.pdf")
    assert result == "Token"
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_image_classifier.py -v`
Expected: FAIL - module not found

**Step 3: Implement image classifier**

Create `backend/grimoire/processors/image_classifier.py`:

```python
"""Classify image-heavy PDFs as Map, Stock Art, Token, etc."""

import re


# Patterns checked against filename AND full path (case-insensitive)
_CLASSIFICATION_RULES = [
    ("Map", [r"map", r"cartograph", r"battlemap", r"battle\s*map", r"dungeon\s*map", r"floorplan", r"floor\s*plan"]),
    ("Token", [r"\btoken", r"\btokens\b"]),
    ("Portrait", [r"portrait"]),
    ("Handout", [r"handout"]),
    ("Scene", [r"\bscene\b"]),
    ("Texture", [r"texture"]),
    ("Stock Art", [r"stock\s*art", r"\bart\s*pack", r"illustration", r"clip\s*art"]),
]


def classify_image_content(filename: str, file_path: str) -> str:
    """
    Classify an image-heavy PDF based on filename and path heuristics.

    Args:
        filename: The PDF filename
        file_path: Full path to the PDF

    Returns:
        Classification string: "Map", "Stock Art", "Token", etc.
        Defaults to "Stock Art" if no pattern matches.
    """
    search_text = f"{filename} {file_path}".lower()

    for label, patterns in _CLASSIFICATION_RULES:
        for pattern in patterns:
            if re.search(pattern, search_text, re.IGNORECASE):
                return label

    return "Stock Art"
```

**Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_image_classifier.py -v`
Expected: PASS

**Step 5: Add `extract_images` queue handler**

In `backend/grimoire/services/queue_processor.py`, add a new handler after `handle_ocr_text_task`:

```python
@register_handler("extract_images")
async def handle_extract_images_task(db: AsyncSession, product: Product) -> bool:
    """Handle image extraction task for maps/stock art PDFs."""
    from grimoire.processors.image_extractor import extract_images
    from grimoire.config import settings

    pdf_path = Path(product.file_path)
    if not pdf_path.exists():
        return False

    output_dir = settings.data_dir / "images" / str(product.id)

    result = await asyncio.to_thread(extract_images, pdf_path, output_dir)

    product.images_extracted = True
    product.image_count = result["image_count"]
    await db.commit()

    logger.info(f"Extracted {result['image_count']} images from product {product.id}")
    return True
```

**Step 6: Modify `handle_text_task` to detect and route image content**

In `backend/grimoire/services/queue_processor.py`, update `handle_text_task` to set `is_image_content` and queue image extraction instead of OCR when image content is detected:

Replace the OCR queueing block (lines 126-137) with:

```python
        if detection["needs_ocr"]:
            # Classify as image content (maps, stock art, etc.)
            from grimoire.processors.image_classifier import classify_image_content
            classification = classify_image_content(product.file_name, product.file_path)

            product.is_image_content = True
            product.product_type = classification

            # Auto-tag with built-in tag
            from grimoire.models import Tag, ProductTag
            tag_result = await db.execute(
                select(Tag).where(Tag.name == classification, Tag.is_builtin == True)
            )
            tag = tag_result.scalar_one_or_none()
            if tag:
                existing_pt = await db.execute(
                    select(ProductTag).where(
                        ProductTag.product_id == product.id,
                        ProductTag.tag_id == tag.id,
                    )
                )
                if not existing_pt.scalar_one_or_none():
                    db.add(ProductTag(
                        product_id=product.id,
                        tag_id=tag.id,
                        source="auto",
                    ))

            # Queue image extraction instead of OCR
            img_item = ProcessingQueue(
                product_id=product.id,
                task_type="extract_images",
                priority=2,
                status="pending",
            )
            db.add(img_item)
            await db.commit()
            logger.info(f"Product {product.id} classified as '{classification}': {detection['reason']}")
            return True
```

**Step 7: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All PASS

**Step 8: Commit**

```bash
git add backend/grimoire/processors/image_classifier.py backend/tests/test_image_classifier.py \
  backend/grimoire/services/queue_processor.py
git commit -m "feat: add image classification and extract_images queue handler"
```

---

### Task 5: Add image serving API routes

**Files:**
- Modify: `backend/grimoire/api/routes/products.py` (add image endpoints)

**Step 1: Write the failing test**

Create `backend/tests/test_image_routes.py`:

```python
"""Tests for image serving API routes."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.mark.asyncio
async def test_list_product_images_no_manifest(db):
    """Should return empty list when no images extracted."""
    from grimoire.models import Product
    p = Product(file_path="/test.pdf", file_name="test.pdf", file_size=1000, file_hash="abc")
    db.add(p)
    await db.commit()
    await db.refresh(p)

    # The route reads from manifest.json - without it, should return empty
    assert p.images_extracted is False
```

**Step 2: Add image routes to products router**

In `backend/grimoire/api/routes/products.py`, add these endpoints:

```python
@router.get("/{product_id}/images")
async def list_product_images(db: DbSession, product_id: int):
    """List extracted images for a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.images_extracted:
        return {"images": [], "image_count": 0, "total_pages": 0}

    manifest_path = settings.data_dir / "images" / str(product.id) / "manifest.json"
    if not manifest_path.exists():
        return {"images": [], "image_count": 0, "total_pages": 0}

    import json
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Add URLs to each image
    for img in manifest.get("images", []):
        img["url"] = f"/api/v1/products/{product_id}/images/{img['filename']}"

    return manifest


@router.get("/{product_id}/images/{filename}")
async def get_product_image(product_id: int, filename: str):
    """Serve a specific extracted image."""
    from fastapi.responses import FileResponse
    import re

    # Validate filename (prevent path traversal)
    if not re.match(r"^\d{3}\.(webp|jpg|jpeg|png)$", filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    image_path = settings.data_dir / "images" / str(product_id) / filename
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    # Determine media type
    suffix = image_path.suffix.lower()
    media_types = {".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(
        path=str(image_path),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
```

Add the settings import at the top of the file if not already present:
```python
from grimoire.config import settings
```

**Step 3: Run tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add backend/grimoire/api/routes/products.py backend/tests/test_image_routes.py
git commit -m "feat: add image listing and serving API endpoints"
```

---

### Task 6: Add gallery API endpoint

**Files:**
- Create: `backend/grimoire/api/routes/gallery.py`
- Modify: `backend/grimoire/api/routes/__init__.py`

**Step 1: Create gallery route**

Create `backend/grimoire/api/routes/gallery.py`:

```python
"""Gallery API endpoint - aggregates image-content products."""

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from grimoire.api.deps import DbSession
from grimoire.models import CollectionProduct, Product, ProductTag, Tag

router = APIRouter()


@router.get("")
async def list_gallery_products(
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    tag_id: int | None = Query(None, description="Filter by tag ID"),
    collection_id: int | None = Query(None, description="Filter by collection ID"),
    sort: str = Query("created_at", description="Sort by: created_at, title, image_count"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    search: str | None = Query(None, description="Search by title or filename"),
):
    """List image-content products for the gallery view."""
    conditions = [Product.is_image_content == True]

    if tag_id:
        conditions.append(
            Product.id.in_(
                select(ProductTag.product_id).where(ProductTag.tag_id == tag_id)
            )
        )

    if collection_id:
        conditions.append(
            Product.id.in_(
                select(CollectionProduct.product_id).where(
                    CollectionProduct.collection_id == collection_id
                )
            )
        )

    if search:
        search_term = f"%{search}%"
        conditions.append(
            (Product.title.ilike(search_term)) | (Product.file_name.ilike(search_term))
        )

    # Count total
    count_query = select(func.count()).select_from(Product).where(*conditions)
    total = (await db.execute(count_query)).scalar() or 0

    # Sort
    sort_column = {
        "created_at": Product.created_at,
        "title": Product.title,
        "image_count": Product.image_count,
    }.get(sort, Product.created_at)

    order_func = sort_column.desc() if order == "desc" else sort_column.asc()

    # Query
    query = (
        select(Product)
        .where(*conditions)
        .order_by(order_func)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(query)
    products = result.scalars().all()

    # Get tags for each product
    product_ids = [p.id for p in products]
    if product_ids:
        tags_query = (
            select(ProductTag.product_id, Tag.id, Tag.name, Tag.color, Tag.is_builtin)
            .join(Tag, ProductTag.tag_id == Tag.id)
            .where(ProductTag.product_id.in_(product_ids))
        )
        tags_result = await db.execute(tags_query)
        product_tags = {}
        for row in tags_result:
            pid = row[0]
            if pid not in product_tags:
                product_tags[pid] = []
            product_tags[pid].append({
                "id": row[1], "name": row[2], "color": row[3], "is_builtin": row[4]
            })
    else:
        product_tags = {}

    items = []
    for p in products:
        items.append({
            "id": p.id,
            "title": p.title or p.file_name,
            "file_name": p.file_name,
            "product_type": p.product_type,
            "image_count": p.image_count or 0,
            "images_extracted": p.images_extracted,
            "cover_extracted": p.cover_extracted,
            "page_count": p.page_count,
            "publisher": p.publisher,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "tags": product_tags.get(p.id, []),
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }
```

**Step 2: Register the gallery router**

In `backend/grimoire/api/routes/__init__.py`, add:

```python
from grimoire.api.routes.gallery import router as gallery_router
```

And in the router includes section:

```python
router.include_router(gallery_router, prefix="/gallery", tags=["gallery"])
```

**Step 3: Run tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add backend/grimoire/api/routes/gallery.py backend/grimoire/api/routes/__init__.py
git commit -m "feat: add gallery API endpoint with filtering and pagination"
```

---

### Task 7: Create frontend gallery API client

**Files:**
- Create: `frontend/src/api/gallery.ts`

**Step 1: Create the API client**

Create `frontend/src/api/gallery.ts`:

```typescript
import client from './client';

export interface GalleryTag {
  id: number;
  name: string;
  color: string | null;
  is_builtin: boolean;
}

export interface GalleryProduct {
  id: number;
  title: string;
  file_name: string;
  product_type: string | null;
  image_count: number;
  images_extracted: boolean;
  cover_extracted: boolean;
  page_count: number | null;
  publisher: string | null;
  created_at: string | null;
  tags: GalleryTag[];
}

export interface GalleryResponse {
  items: GalleryProduct[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface GalleryFilters {
  page?: number;
  page_size?: number;
  tag_id?: number;
  collection_id?: number;
  sort?: 'created_at' | 'title' | 'image_count';
  order?: 'asc' | 'desc';
  search?: string;
}

export interface ProductImage {
  filename: string;
  page: number;
  width: number;
  height: number;
  original_format: string;
  file_size: number;
  url: string;
}

export interface ProductImagesResponse {
  images: ProductImage[];
  image_count: number;
  total_pages: number;
}

export async function getGalleryProducts(filters: GalleryFilters = {}): Promise<GalleryResponse> {
  const params = new URLSearchParams();
  if (filters.page) params.set('page', String(filters.page));
  if (filters.page_size) params.set('page_size', String(filters.page_size));
  if (filters.tag_id) params.set('tag_id', String(filters.tag_id));
  if (filters.collection_id) params.set('collection_id', String(filters.collection_id));
  if (filters.sort) params.set('sort', filters.sort);
  if (filters.order) params.set('order', filters.order);
  if (filters.search) params.set('search', filters.search);

  const { data } = await client.get(`/gallery?${params.toString()}`);
  return data;
}

export async function getProductImages(productId: number): Promise<ProductImagesResponse> {
  const { data } = await client.get(`/products/${productId}/images`);
  return data;
}

export function getImageUrl(productId: number, filename: string): string {
  return `/api/v1/products/${productId}/images/${filename}`;
}
```

**Step 2: Commit**

```bash
git add frontend/src/api/gallery.ts
git commit -m "feat: add gallery API client for frontend"
```

---

### Task 8: Create Gallery page component

**Files:**
- Create: `frontend/src/pages/Gallery.tsx`
- Modify: `frontend/src/App.tsx`

**Step 1: Create the Gallery page**

Create `frontend/src/pages/Gallery.tsx`:

```tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Image, Search, X, ChevronLeft, ChevronRight, Grid3X3, Loader2 } from 'lucide-react';
import { getGalleryProducts, getProductImages, getImageUrl } from '../api/gallery';
import { getTags } from '../api/tags';
import { getCollections } from '../api/collections';
import { getThumbnailUrl } from '../api/products';
import type { GalleryFilters, GalleryProduct, ProductImage } from '../api/gallery';

export function Gallery() {
  const [filters, setFilters] = useState<GalleryFilters>({ page: 1, page_size: 24 });
  const [searchInput, setSearchInput] = useState('');
  const [expandedProduct, setExpandedProduct] = useState<GalleryProduct | null>(null);

  const { data: gallery, isLoading } = useQuery({
    queryKey: ['gallery', filters],
    queryFn: () => getGalleryProducts(filters),
  });

  const { data: tags } = useQuery({
    queryKey: ['tags'],
    queryFn: () => getTags(),
  });

  const { data: collections } = useQuery({
    queryKey: ['collections'],
    queryFn: () => getCollections(),
  });

  const builtinTags = tags?.filter(t => t.is_builtin) || [];

  const handleSearch = () => {
    setFilters(prev => ({ ...prev, search: searchInput || undefined, page: 1 }));
  };

  const handleTagFilter = (tagId: number | undefined) => {
    setFilters(prev => ({ ...prev, tag_id: tagId, page: 1 }));
  };

  const handleCollectionFilter = (collectionId: number | undefined) => {
    setFilters(prev => ({ ...prev, collection_id: collectionId, page: 1 }));
  };

  return (
    <div className="flex h-full">
      {/* Sidebar filters */}
      <div className="w-64 flex-shrink-0 overflow-y-auto border-r border-primary-300 bg-primary-200 p-4">
        {/* Search */}
        <div className="mb-6">
          <label className="mb-2 block text-sm font-medium text-primary-700">Search</label>
          <div className="flex gap-1">
            <input
              type="text"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="Search gallery..."
              className="flex-1 rounded border border-primary-300 bg-primary-100 px-2 py-1 text-sm text-primary-800"
            />
            <button onClick={handleSearch} className="rounded bg-codex-olive p-1 text-codex-cream">
              <Search className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Content type tags */}
        <div className="mb-6">
          <label className="mb-2 block text-sm font-medium text-primary-700">Content Type</label>
          <div className="flex flex-col gap-1">
            <button
              onClick={() => handleTagFilter(undefined)}
              className={`rounded px-2 py-1 text-left text-sm ${
                !filters.tag_id ? 'bg-codex-olive text-codex-cream' : 'text-primary-700 hover:bg-primary-300'
              }`}
            >
              All
            </button>
            {builtinTags.map(tag => (
              <button
                key={tag.id}
                onClick={() => handleTagFilter(tag.id)}
                className={`rounded px-2 py-1 text-left text-sm ${
                  filters.tag_id === tag.id ? 'bg-codex-olive text-codex-cream' : 'text-primary-700 hover:bg-primary-300'
                }`}
              >
                <span
                  className="mr-2 inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: tag.color || '#888' }}
                />
                {tag.name}
                {tag.product_count > 0 && (
                  <span className="ml-1 text-xs opacity-60">({tag.product_count})</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Collections */}
        {collections && collections.length > 0 && (
          <div className="mb-6">
            <label className="mb-2 block text-sm font-medium text-primary-700">Collections</label>
            <div className="flex flex-col gap-1">
              <button
                onClick={() => handleCollectionFilter(undefined)}
                className={`rounded px-2 py-1 text-left text-sm ${
                  !filters.collection_id ? 'bg-codex-olive text-codex-cream' : 'text-primary-700 hover:bg-primary-300'
                }`}
              >
                All
              </button>
              {collections.map(col => (
                <button
                  key={col.id}
                  onClick={() => handleCollectionFilter(col.id)}
                  className={`rounded px-2 py-1 text-left text-sm ${
                    filters.collection_id === col.id ? 'bg-codex-olive text-codex-cream' : 'text-primary-700 hover:bg-primary-300'
                  }`}
                >
                  {col.name}
                  {col.product_count > 0 && (
                    <span className="ml-1 text-xs opacity-60">({col.product_count})</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Sort */}
        <div>
          <label className="mb-2 block text-sm font-medium text-primary-700">Sort By</label>
          <select
            value={`${filters.sort || 'created_at'}-${filters.order || 'desc'}`}
            onChange={e => {
              const [sort, order] = e.target.value.split('-');
              setFilters(prev => ({ ...prev, sort: sort as any, order: order as any }));
            }}
            className="w-full rounded border border-primary-300 bg-primary-100 px-2 py-1 text-sm text-primary-800"
          >
            <option value="created_at-desc">Newest First</option>
            <option value="created_at-asc">Oldest First</option>
            <option value="title-asc">Title A-Z</option>
            <option value="title-desc">Title Z-A</option>
            <option value="image_count-desc">Most Images</option>
          </select>
        </div>
      </div>

      {/* Main grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-primary-500" />
          </div>
        ) : !gallery || gallery.items.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-primary-500">
            <Image className="mb-4 h-16 w-16 opacity-50" />
            <p className="text-lg">No image content found</p>
            <p className="text-sm">Maps and stock art PDFs will appear here after scanning</p>
          </div>
        ) : (
          <>
            <div className="mb-4 text-sm text-primary-600">
              {gallery.total} product{gallery.total !== 1 ? 's' : ''} found
            </div>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
              {gallery.items.map(product => (
                <GalleryCard
                  key={product.id}
                  product={product}
                  onClick={() => setExpandedProduct(product)}
                />
              ))}
            </div>
            {/* Pagination */}
            {gallery.total_pages > 1 && (
              <div className="mt-6 flex items-center justify-center gap-2">
                <button
                  onClick={() => setFilters(prev => ({ ...prev, page: (prev.page || 1) - 1 }))}
                  disabled={gallery.page <= 1}
                  className="rounded bg-primary-300 p-2 text-primary-700 disabled:opacity-50"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="text-sm text-primary-600">
                  Page {gallery.page} of {gallery.total_pages}
                </span>
                <button
                  onClick={() => setFilters(prev => ({ ...prev, page: (prev.page || 1) + 1 }))}
                  disabled={gallery.page >= gallery.total_pages}
                  className="rounded bg-primary-300 p-2 text-primary-700 disabled:opacity-50"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Expanded product modal */}
      {expandedProduct && (
        <ProductImageModal
          product={expandedProduct}
          onClose={() => setExpandedProduct(null)}
        />
      )}
    </div>
  );
}


function GalleryCard({ product, onClick }: { product: GalleryProduct; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="group overflow-hidden rounded-lg border border-primary-300 bg-primary-200 text-left transition-shadow hover:shadow-lg"
    >
      <div className="aspect-[3/4] overflow-hidden bg-primary-300">
        {product.cover_extracted ? (
          <img
            src={getThumbnailUrl(product.id)}
            alt={product.title}
            className="h-full w-full object-cover transition-transform group-hover:scale-105"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <Image className="h-12 w-12 text-primary-500" />
          </div>
        )}
      </div>
      <div className="p-2">
        <p className="truncate text-sm font-medium text-primary-800">{product.title}</p>
        <div className="mt-1 flex items-center gap-1">
          {product.tags.slice(0, 2).map(tag => (
            <span
              key={tag.id}
              className="rounded px-1.5 py-0.5 text-xs text-white"
              style={{ backgroundColor: tag.color || '#888' }}
            >
              {tag.name}
            </span>
          ))}
          {product.image_count > 0 && (
            <span className="ml-auto flex items-center gap-0.5 text-xs text-primary-500">
              <Grid3X3 className="h-3 w-3" />
              {product.image_count}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}


function ProductImageModal({ product, onClose }: { product: GalleryProduct; onClose: () => void }) {
  const { data: imagesData, isLoading } = useQuery({
    queryKey: ['product-images', product.id],
    queryFn: () => getProductImages(product.id),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-8" onClick={onClose}>
      <div
        className="w-full max-w-6xl rounded-lg bg-primary-100 shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-primary-300 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-primary-800">{product.title}</h2>
            {product.publisher && (
              <p className="text-sm text-primary-600">{product.publisher}</p>
            )}
          </div>
          <button onClick={onClose} className="rounded p-1 text-primary-500 hover:bg-primary-300">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Images grid */}
        <div className="p-6">
          {isLoading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary-500" />
            </div>
          ) : !imagesData || imagesData.images.length === 0 ? (
            <div className="py-12 text-center text-primary-500">
              <p>No images extracted yet</p>
              <p className="mt-1 text-sm">Images will appear after processing completes</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
              {imagesData.images.map((img, i) => (
                <ImageTile key={i} image={img} productId={product.id} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


function ImageTile({ image, productId }: { image: ProductImage; productId: number }) {
  const [fullscreen, setFullscreen] = useState(false);
  const url = getImageUrl(productId, image.filename);

  return (
    <>
      <button
        onClick={() => setFullscreen(true)}
        className="group overflow-hidden rounded border border-primary-300 bg-primary-200"
      >
        <img
          src={url}
          alt={`Page ${image.page}`}
          className="w-full transition-transform group-hover:scale-105"
          loading="lazy"
        />
        <div className="px-2 py-1 text-xs text-primary-600">
          Page {image.page} &middot; {image.width}x{image.height}
        </div>
      </button>

      {fullscreen && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/90 p-4"
          onClick={() => setFullscreen(false)}
        >
          <img
            src={url}
            alt={`Page ${image.page}`}
            className="max-h-full max-w-full object-contain"
          />
        </div>
      )}
    </>
  );
}
```

**Step 2: Wire up Gallery in App.tsx**

In `frontend/src/App.tsx`:

Add import:
```typescript
import { Gallery } from './pages/Gallery';
```

Add gallery view to the main content render (after line 81, before the Library fallback):

```tsx
          ) : activeView === 'gallery' ? (
            <Gallery />
```

**Step 3: Add Gallery to sidebar navigation**

Check `frontend/src/components/Sidebar.tsx` for how navigation items are added and add a "Gallery" item with the Image icon that sets `activeView` to `'gallery'`.

**Step 4: Commit**

```bash
git add frontend/src/pages/Gallery.tsx frontend/src/App.tsx frontend/src/components/Sidebar.tsx
git commit -m "feat: add gallery page with image grid and product modal"
```

---

### Task 9: Update frontend Tag API types for `is_builtin`

**Files:**
- Modify: `frontend/src/api/tags.ts`

**Step 1: Add `is_builtin` to Tag interface**

In `frontend/src/api/tags.ts`, add `is_builtin: boolean` to the `Tag` interface.

**Step 2: Commit**

```bash
git add frontend/src/api/tags.ts
git commit -m "feat: add is_builtin field to Tag interface"
```

---

### Task 10: End-to-end verification

**Step 1: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All PASS

**Step 2: Run frontend build check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Manual test**

1. Start the backend: `cd backend && python -m grimoire`
2. Start the frontend: `cd frontend && npm run dev`
3. Scan a folder containing map/stock art PDFs
4. Verify in logs that image-heavy PDFs are classified as "Map" or "Stock Art"
5. Verify `extract_images` tasks appear in the processing queue
6. After processing, navigate to the Gallery view
7. Verify products appear with thumbnails, tags, and image counts
8. Click a product to open the modal and verify extracted images display

**Step 4: Final commit**

```bash
git commit -m "feat: complete image gallery with auto-classification and extraction"
```
