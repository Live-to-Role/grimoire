# Product Reclassification Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow bulk reclassification of products between regular and image content, with auto-tagging and extraction queuing.

**Architecture:** Extend the existing `BulkUpdateRequest` with `is_image_content`, `content_type`, and `re_extract` fields. Add a tag_service helper for content-type tag management. Frontend gets an Image Content toggle + Content Type dropdown in BulkEditModal.

**Tech Stack:** FastAPI, Pydantic v2 (model_validator), SQLAlchemy async, React 18, TypeScript, React Query v5

**Spec:** `backend/docs/superpowers/specs/2026-03-14-product-reclassification-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/grimoire/services/tag_service.py` | Modify | Add `BUILTIN_TAG_NAMES`, `set_content_type_tag()`, `remove_content_type_tags()` helpers |
| `backend/grimoire/api/routes/bulk.py` | Modify | Extend `BulkUpdateRequest` with reclassification fields + handler logic |
| `backend/tests/api/test_bulk_reclassify.py` | Create | Reclassification test scenarios |
| `frontend/src/api/products.ts` | Modify | Add `is_image_content`, `content_type`, `re_extract` to `BulkUpdateFields` |
| `frontend/src/components/BulkEditModal.tsx` | Modify | Image Content toggle, Content Type dropdown, preview additions, gallery invalidation |

---

## Chunk 1: Backend — Tag Service Helpers

### Task 1: Tag Service — Content Type Helpers

**Files:**
- Modify: `backend/grimoire/services/tag_service.py`
- Test: `backend/tests/api/test_bulk_reclassify.py`

- [ ] **Step 1: Create test file with tag helper tests**

Create `backend/tests/api/test_bulk_reclassify.py`:

```python
"""Tests for product reclassification via bulk update."""
import pytest
from sqlalchemy import select

from grimoire.models import Product, Tag, ProductTag, ProcessingQueue
from grimoire.services.tag_service import (
    BUILTIN_TAG_NAMES,
    seed_builtin_tags,
    set_content_type_tag,
    remove_content_type_tags,
)


@pytest.fixture
async def seeded_tags(db):
    """Seed builtin tags and return them."""
    await seed_builtin_tags(db)
    result = await db.execute(select(Tag).where(Tag.is_builtin == True))
    return {t.name: t for t in result.scalars().all()}


@pytest.fixture
async def reclassify_products(db, seeded_tags, request):
    """Create test products for reclassification tests."""
    prefix = request.node.name
    products = []
    for i in range(3):
        p = Product(
            file_path=f"/test/{prefix}/map_{i}.pdf",
            file_name=f"map_{i}.pdf",
            file_size=1000,
            file_hash=f"{prefix}_hash_{i}",
            is_image_content=False,
            images_extracted=False,
        )
        db.add(p)
    await db.commit()
    result = await db.execute(
        select(Product).where(Product.file_path.like(f"/test/{prefix}/%"))
    )
    return list(result.scalars().all())


class TestBuiltinTagNames:
    def test_builtin_tag_names_has_all_eight(self):
        assert len(BUILTIN_TAG_NAMES) == 8
        assert "Map" in BUILTIN_TAG_NAMES
        assert "Stock Art" in BUILTIN_TAG_NAMES


class TestSetContentTypeTag:
    @pytest.mark.asyncio
    async def test_set_content_type_tag_creates_auto_tag(self, db, seeded_tags, reclassify_products):
        product = reclassify_products[0]
        await set_content_type_tag(db, product.id, "Map")

        result = await db.execute(
            select(ProductTag).where(
                ProductTag.product_id == product.id,
                ProductTag.tag_id == seeded_tags["Map"].id,
            )
        )
        pt = result.scalar_one()
        assert pt.source == "auto"

    @pytest.mark.asyncio
    async def test_set_content_type_tag_removes_old_auto_tags(self, db, seeded_tags, reclassify_products):
        product = reclassify_products[0]
        # Set to Map first
        await set_content_type_tag(db, product.id, "Map")
        # Change to Token
        await set_content_type_tag(db, product.id, "Token")

        # Map tag should be gone
        result = await db.execute(
            select(ProductTag).where(
                ProductTag.product_id == product.id,
                ProductTag.tag_id == seeded_tags["Map"].id,
            )
        )
        assert result.scalar_one_or_none() is None

        # Token tag should exist
        result = await db.execute(
            select(ProductTag).where(
                ProductTag.product_id == product.id,
                ProductTag.tag_id == seeded_tags["Token"].id,
            )
        )
        assert result.scalar_one().source == "auto"

    @pytest.mark.asyncio
    async def test_set_content_type_tag_preserves_user_tags(self, db, seeded_tags, reclassify_products):
        product = reclassify_products[0]
        # Manually tag with Map (user source)
        db.add(ProductTag(product_id=product.id, tag_id=seeded_tags["Map"].id, source="user"))
        await db.flush()

        # Set content type to Token — should NOT remove user's Map tag
        await set_content_type_tag(db, product.id, "Token")

        result = await db.execute(
            select(ProductTag).where(
                ProductTag.product_id == product.id,
                ProductTag.tag_id == seeded_tags["Map"].id,
            )
        )
        assert result.scalar_one().source == "user"


class TestRemoveContentTypeTags:
    @pytest.mark.asyncio
    async def test_removes_auto_content_type_tags(self, db, seeded_tags, reclassify_products):
        product = reclassify_products[0]
        db.add(ProductTag(product_id=product.id, tag_id=seeded_tags["Map"].id, source="auto"))
        await db.flush()

        await remove_content_type_tags(db, product.id)

        result = await db.execute(
            select(ProductTag).where(ProductTag.product_id == product.id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_preserves_non_auto_tags(self, db, seeded_tags, reclassify_products):
        product = reclassify_products[0]
        db.add(ProductTag(product_id=product.id, tag_id=seeded_tags["Map"].id, source="user"))
        await db.flush()

        await remove_content_type_tags(db, product.id)

        result = await db.execute(
            select(ProductTag).where(ProductTag.product_id == product.id)
        )
        assert result.scalar_one().source == "user"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/api/test_bulk_reclassify.py -v -x`
Expected: ImportError — `BUILTIN_TAG_NAMES`, `set_content_type_tag`, `remove_content_type_tags` don't exist yet

- [ ] **Step 3: Implement tag service helpers**

Add to `backend/grimoire/services/tag_service.py` after the existing `BUILTIN_TAGS` list:

```python
BUILTIN_TAG_NAMES = {t["name"] for t in BUILTIN_TAGS}
```

Add two new functions after `seed_builtin_tags`:

```python
async def set_content_type_tag(
    db: AsyncSession, product_id: int, content_type: str
) -> None:
    """Remove existing auto content-type tags and set the new one.

    Only removes tags with source="auto" on builtin content_type tags.
    User-applied tags are preserved.
    """
    from grimoire.models import ProductTag

    # Remove existing auto content-type tags
    await remove_content_type_tags(db, product_id)

    # Find the target tag
    result = await db.execute(
        select(Tag).where(Tag.name == content_type, Tag.is_builtin == True)
    )
    tag = result.scalar_one()

    # Check if already tagged (e.g., user-applied)
    existing = await db.execute(
        select(ProductTag).where(
            ProductTag.product_id == product_id,
            ProductTag.tag_id == tag.id,
        )
    )
    if not existing.scalar_one_or_none():
        db.add(ProductTag(product_id=product_id, tag_id=tag.id, source="auto"))


async def remove_content_type_tags(db: AsyncSession, product_id: int) -> None:
    """Remove all auto-sourced builtin content-type tags from a product."""
    from grimoire.models import ProductTag

    # Get all builtin content_type tag IDs
    result = await db.execute(
        select(Tag.id).where(Tag.category == "content_type", Tag.is_builtin == True)
    )
    builtin_tag_ids = [row[0] for row in result.all()]

    if not builtin_tag_ids:
        return

    # Delete auto-sourced content-type tags
    result = await db.execute(
        select(ProductTag).where(
            ProductTag.product_id == product_id,
            ProductTag.tag_id.in_(builtin_tag_ids),
            ProductTag.source == "auto",
        )
    )
    for pt in result.scalars().all():
        await db.delete(pt)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/api/test_bulk_reclassify.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/tag_service.py backend/tests/api/test_bulk_reclassify.py
git commit -m "feat: add content-type tag helpers to tag_service"
```

---

## Chunk 2: Backend — Bulk Update Reclassification Logic

### Task 2: Extend BulkUpdateRequest Schema

**Files:**
- Modify: `backend/grimoire/api/routes/bulk.py:1-47`

- [ ] **Step 1: Write validation tests**

Append to `backend/tests/api/test_bulk_reclassify.py`:

```python
class TestBulkUpdateRequestValidation:
    def test_is_image_content_true_requires_content_type(self):
        from pydantic import ValidationError
        from grimoire.api.routes.bulk import BulkUpdateRequest

        with pytest.raises(ValidationError, match="content_type is required"):
            BulkUpdateRequest(
                product_ids=[1],
                is_image_content=True,
            )

    def test_is_image_content_true_with_valid_content_type(self):
        from grimoire.api.routes.bulk import BulkUpdateRequest

        req = BulkUpdateRequest(
            product_ids=[1],
            is_image_content=True,
            content_type="Map",
        )
        assert req.is_image_content is True
        assert req.content_type == "Map"

    def test_is_image_content_true_rejects_invalid_content_type(self):
        from pydantic import ValidationError
        from grimoire.api.routes.bulk import BulkUpdateRequest

        with pytest.raises(ValidationError, match="must be one of"):
            BulkUpdateRequest(
                product_ids=[1],
                is_image_content=True,
                content_type="InvalidType",
            )

    def test_is_image_content_false_ignores_content_type(self):
        from grimoire.api.routes.bulk import BulkUpdateRequest

        req = BulkUpdateRequest(
            product_ids=[1],
            is_image_content=False,
            content_type="Map",  # accepted but ignored by handler
        )
        assert req.is_image_content is False
        # content_type passes validation but handler ignores it when is_image_content=False
        assert req.content_type == "Map"

    def test_is_image_content_true_with_product_type_uses_content_type(self):
        """Spec: product_type is ignored when is_image_content=True (content_type wins)."""
        from grimoire.api.routes.bulk import BulkUpdateRequest

        req = BulkUpdateRequest(
            product_ids=[1],
            is_image_content=True,
            content_type="Map",
            product_type="Adventure",  # should be overridden
        )
        assert req.is_image_content is True
        assert req.content_type == "Map"

    def test_unchanged_omits_is_image_content(self):
        from grimoire.api.routes.bulk import BulkUpdateRequest

        req = BulkUpdateRequest(product_ids=[1], game_system="D&D 5e")
        assert "is_image_content" not in req.model_fields_set
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/api/test_bulk_reclassify.py::TestBulkUpdateRequestValidation -v -x`
Expected: FAIL — no `is_image_content` field on BulkUpdateRequest

- [ ] **Step 3: Extend BulkUpdateRequest with new fields and validator**

In `backend/grimoire/api/routes/bulk.py`, update the import and schema:

Add `model_validator` to the pydantic import:
```python
from pydantic import BaseModel, Field, model_validator
```

Add new fields and validator to `BulkUpdateRequest` (after `format` field, before class close):

```python
    # Reclassification fields
    is_image_content: bool | None = None
    content_type: str | None = None
    re_extract: bool = False

    @model_validator(mode="after")
    def validate_reclassification(self) -> "BulkUpdateRequest":
        if self.is_image_content is True:
            if not self.content_type:
                raise ValueError("content_type is required when is_image_content is True")
            from grimoire.services.tag_service import BUILTIN_TAG_NAMES
            if self.content_type not in BUILTIN_TAG_NAMES:
                raise ValueError(
                    f"content_type must be one of: {', '.join(sorted(BUILTIN_TAG_NAMES))}"
                )
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/api/test_bulk_reclassify.py::TestBulkUpdateRequestValidation -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/api/routes/bulk.py backend/tests/api/test_bulk_reclassify.py
git commit -m "feat: extend BulkUpdateRequest with reclassification fields"
```

### Task 3: Reclassify-to-Image-Content Handler Logic

**Files:**
- Modify: `backend/grimoire/api/routes/bulk.py:188-243`
- Test: `backend/tests/api/test_bulk_reclassify.py`

- [ ] **Step 1: Write reclassify-to-image tests**

Append to `backend/tests/api/test_bulk_reclassify.py`:

```python
class TestReclassifyToImageContent:
    @pytest.mark.asyncio
    async def test_sets_image_content_fields(self, db, seeded_tags, reclassify_products):
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        product_ids = [p.id for p in reclassify_products]
        req = BulkUpdateRequest(
            product_ids=product_ids,
            is_image_content=True,
            content_type="Map",
        )
        response = await bulk_update_products(db, req)

        assert response.affected == 3
        for p in reclassify_products:
            await db.refresh(p)
            assert p.is_image_content is True
            assert p.product_type == "Map"

    @pytest.mark.asyncio
    async def test_creates_auto_tag(self, db, seeded_tags, reclassify_products):
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        req = BulkUpdateRequest(
            product_ids=[reclassify_products[0].id],
            is_image_content=True,
            content_type="Map",
        )
        await bulk_update_products(db, req)

        result = await db.execute(
            select(ProductTag).where(
                ProductTag.product_id == reclassify_products[0].id,
                ProductTag.tag_id == seeded_tags["Map"].id,
                ProductTag.source == "auto",
            )
        )
        assert result.scalar_one() is not None

    @pytest.mark.asyncio
    async def test_queues_extraction(self, db, seeded_tags, reclassify_products):
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        req = BulkUpdateRequest(
            product_ids=[reclassify_products[0].id],
            is_image_content=True,
            content_type="Map",
        )
        await bulk_update_products(db, req)

        result = await db.execute(
            select(ProcessingQueue).where(
                ProcessingQueue.product_id == reclassify_products[0].id,
                ProcessingQueue.task_type == "extract_images",
            )
        )
        task = result.scalar_one()
        assert task.status == "pending"
        assert task.priority == 2

    @pytest.mark.asyncio
    async def test_skips_extraction_when_already_extracted(self, db, seeded_tags, reclassify_products):
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        reclassify_products[0].images_extracted = True
        await db.flush()

        req = BulkUpdateRequest(
            product_ids=[reclassify_products[0].id],
            is_image_content=True,
            content_type="Map",
        )
        await bulk_update_products(db, req)

        result = await db.execute(
            select(ProcessingQueue).where(
                ProcessingQueue.product_id == reclassify_products[0].id,
                ProcessingQueue.task_type == "extract_images",
            )
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_re_extract_queues_already_extracted(self, db, seeded_tags, reclassify_products):
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        reclassify_products[0].images_extracted = True
        await db.flush()

        req = BulkUpdateRequest(
            product_ids=[reclassify_products[0].id],
            is_image_content=True,
            content_type="Map",
            re_extract=True,
        )
        await bulk_update_products(db, req)

        result = await db.execute(
            select(ProcessingQueue).where(
                ProcessingQueue.product_id == reclassify_products[0].id,
                ProcessingQueue.task_type == "extract_images",
            )
        )
        assert result.scalar_one() is not None

    @pytest.mark.asyncio
    async def test_no_duplicate_queue_entries(self, db, seeded_tags, reclassify_products):
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        # Add existing pending task
        db.add(ProcessingQueue(
            product_id=reclassify_products[0].id,
            task_type="extract_images",
            status="pending",
            priority=2,
        ))
        await db.flush()

        req = BulkUpdateRequest(
            product_ids=[reclassify_products[0].id],
            is_image_content=True,
            content_type="Map",
        )
        await bulk_update_products(db, req)

        result = await db.execute(
            select(ProcessingQueue).where(
                ProcessingQueue.product_id == reclassify_products[0].id,
                ProcessingQueue.task_type == "extract_images",
            )
        )
        tasks = list(result.scalars().all())
        assert len(tasks) == 1

    @pytest.mark.asyncio
    async def test_response_message_includes_queue_count(self, db, seeded_tags, reclassify_products):
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        req = BulkUpdateRequest(
            product_ids=[p.id for p in reclassify_products],
            is_image_content=True,
            content_type="Map",
        )
        response = await bulk_update_products(db, req)
        assert "Queued 3" in response.message

    @pytest.mark.asyncio
    async def test_product_type_overridden_by_content_type(self, db, seeded_tags, reclassify_products):
        """Spec: product_type is ignored when is_image_content=True; content_type wins."""
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        p = reclassify_products[0]
        req = BulkUpdateRequest(
            product_ids=[p.id],
            is_image_content=True,
            content_type="Map",
            product_type="Adventure",  # should be overridden
        )
        await bulk_update_products(db, req)
        await db.refresh(p)
        assert p.product_type == "Map"  # content_type wins
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/api/test_bulk_reclassify.py::TestReclassifyToImageContent -v -x`
Expected: FAIL — handler doesn't process reclassification fields yet

- [ ] **Step 3: Implement reclassify-to-image logic in handler**

In `backend/grimoire/api/routes/bulk.py`, modify the `bulk_update_products` handler. Add `ProcessingQueue` to the model imports at line 9:

```python
from grimoire.models import Product, Tag, ProductTag, Collection, CollectionProduct, ProcessingQueue
```

In the `bulk_update_products` function, after the existing field update loop (after `if updated: affected += 1`) and before `await db.commit()`, add the reclassification logic:

```python
    # Handle reclassification
    queued_count = 0

    if "is_image_content" in provided_fields and request.is_image_content is True:
        from grimoire.services.tag_service import set_content_type_tag

        for product in products:
            product.is_image_content = True
            product.product_type = request.content_type
            await set_content_type_tag(db, product.id, request.content_type)

            # Queue extraction if not already extracted (or re_extract requested)
            should_extract = not product.images_extracted or request.re_extract
            if should_extract:
                # Duplicate check
                existing_task = await db.execute(
                    select(ProcessingQueue).where(
                        ProcessingQueue.product_id == product.id,
                        ProcessingQueue.task_type == "extract_images",
                        ProcessingQueue.status.in_(["pending", "processing"]),
                    )
                )
                if not existing_task.scalar_one_or_none():
                    db.add(ProcessingQueue(
                        product_id=product.id,
                        task_type="extract_images",
                        priority=2,
                        status="pending",
                    ))
                    queued_count += 1

        affected = len(products)
        filter_fields_updated = True
```

**Note:** The return statement and cache invalidation are restructured in Task 4 Step 3 (commit flow). For now, just add the reclassification block above the existing `await db.commit()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/api/test_bulk_reclassify.py::TestReclassifyToImageContent -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/api/routes/bulk.py backend/tests/api/test_bulk_reclassify.py
git commit -m "feat: implement reclassify-to-image-content in bulk update"
```

### Task 4: Reclassify-to-Regular Handler Logic

**Files:**
- Modify: `backend/grimoire/api/routes/bulk.py`
- Test: `backend/tests/api/test_bulk_reclassify.py`

- [ ] **Step 1: Write reclassify-to-regular tests**

Append to `backend/tests/api/test_bulk_reclassify.py`:

```python
class TestReclassifyToRegular:
    @pytest.mark.asyncio
    async def test_clears_image_content_fields(self, db, seeded_tags, reclassify_products):
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        # Set up as image content first
        p = reclassify_products[0]
        p.is_image_content = True
        p.product_type = "Map"
        p.images_extracted = True
        p.image_count = 5
        await db.flush()

        req = BulkUpdateRequest(
            product_ids=[p.id],
            is_image_content=False,
        )
        await bulk_update_products(db, req)
        await db.refresh(p)

        assert p.is_image_content is False
        assert p.product_type is None
        assert p.images_extracted is False
        assert p.image_count is None

    @pytest.mark.asyncio
    async def test_removes_auto_content_type_tags(self, db, seeded_tags, reclassify_products):
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        p = reclassify_products[0]
        db.add(ProductTag(product_id=p.id, tag_id=seeded_tags["Map"].id, source="auto"))
        await db.flush()

        req = BulkUpdateRequest(
            product_ids=[p.id],
            is_image_content=False,
        )
        await bulk_update_products(db, req)

        result = await db.execute(
            select(ProductTag).where(
                ProductTag.product_id == p.id,
                ProductTag.source == "auto",
            )
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_deletes_image_directory(self, db, seeded_tags, reclassify_products, tmp_path):
        """Image directory deletion is tested via mock to avoid filesystem deps."""
        from unittest.mock import patch, MagicMock
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        p = reclassify_products[0]
        p.is_image_content = True
        p.images_extracted = True
        await db.flush()

        with patch("grimoire.api.routes.bulk.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            image_dir = tmp_path / "images" / str(p.id)
            image_dir.mkdir(parents=True)
            (image_dir / "page_1.png").write_bytes(b"fake")

            req = BulkUpdateRequest(
                product_ids=[p.id],
                is_image_content=False,
            )
            await bulk_update_products(db, req)

            assert not image_dir.exists()

    @pytest.mark.asyncio
    async def test_image_dir_missing_no_error(self, db, seeded_tags, reclassify_products, tmp_path):
        """Should not error if image directory doesn't exist."""
        from unittest.mock import patch
        from grimoire.api.routes.bulk import BulkUpdateRequest, bulk_update_products

        p = reclassify_products[0]
        p.is_image_content = True
        await db.flush()

        with patch("grimoire.api.routes.bulk.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            # Don't create the directory — should still succeed

            req = BulkUpdateRequest(
                product_ids=[p.id],
                is_image_content=False,
            )
            response = await bulk_update_products(db, req)
            assert response.affected == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/api/test_bulk_reclassify.py::TestReclassifyToRegular -v -x`
Expected: FAIL — handler doesn't handle `is_image_content=False` yet

- [ ] **Step 3: Implement reclassify-to-regular logic**

In `backend/grimoire/api/routes/bulk.py`, add to the top of the file (after existing imports):

```python
import logging
import shutil

from grimoire.config import settings

logger = logging.getLogger(__name__)
```

**Note:** `settings` is imported at module level so tests can mock it via `patch("grimoire.api.routes.bulk.settings")`.

In the `bulk_update_products` handler, after the `is_image_content is True` block and before `await db.commit()`, add:

```python
    elif "is_image_content" in provided_fields and request.is_image_content is False:
        from grimoire.services.tag_service import remove_content_type_tags

        for product in products:
            product.is_image_content = False
            product.product_type = None
            product.images_extracted = False
            product.image_count = None
            await remove_content_type_tags(db, product.id)

        affected = len(products)
        filter_fields_updated = True
```

**Restructure commit flow:** Replace the existing `await db.commit()` and everything after it with a single unified flow using a `committed` flag:

```python
    # Commit
    committed = False

    # Reclassify-to-regular needs commit before filesystem cleanup
    if "is_image_content" in provided_fields and request.is_image_content is False:
        await db.commit()
        committed = True

        # Delete extracted image directories (after commit, so DB is authoritative)
        for product in products:
            image_dir = settings.data_dir / "images" / str(product.id)
            if image_dir.exists():
                try:
                    shutil.rmtree(image_dir)
                except OSError as e:
                    logger.warning("Failed to delete image dir %s: %s", image_dir, e)

    if not committed:
        await db.commit()

    # Invalidate filter cache if filter-relevant fields were updated
    if filter_fields_updated:
        from grimoire.services.cache_service import get_cache_service
        cache = await get_cache_service()
        await cache.invalidate_filter_options()

    message = "Updated products"
    if queued_count > 0:
        message = f"Updated {affected} products. Queued {queued_count} for image extraction."

    return BulkResponse(
        message=message,
        affected=affected,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/api/test_bulk_reclassify.py::TestReclassifyToRegular -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/api/routes/bulk.py backend/tests/api/test_bulk_reclassify.py
git commit -m "feat: implement reclassify-to-regular in bulk update with image cleanup"
```

---

## Chunk 3: Frontend — API Types and BulkEditModal

### Task 5: Extend Frontend API Types

**Files:**
- Modify: `frontend/src/api/products.ts:93-104`

- [ ] **Step 1: Add reclassification fields to BulkUpdateFields**

In `frontend/src/api/products.ts`, add three fields to the `BulkUpdateFields` interface:

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
  // Reclassification
  is_image_content?: boolean;
  content_type?: string;
  re_extract?: boolean;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/products.ts
git commit -m "feat: add reclassification fields to BulkUpdateFields"
```

### Task 6: BulkEditModal — Image Content Toggle and Content Type Dropdown

**Files:**
- Modify: `frontend/src/components/BulkEditModal.tsx`

- [ ] **Step 1: Add reclassification state**

In `BulkEditModal.tsx`, add state variables after the existing `view` state (line 45):

```typescript
  const [imageContentToggle, setImageContentToggle] = useState<'unchanged' | 'yes' | 'no'>('unchanged');
  const [contentType, setContentType] = useState<string>('');
  const [reExtract, setReExtract] = useState(false);
```

Add the content type options constant above the component (after `RIGHT_FIELDS`):

```typescript
const CONTENT_TYPES = ['Map', 'Stock Art', 'Token', 'Handout', 'Portrait', 'Scene', 'Item', 'Texture'];
```

- [ ] **Step 2: Add reclassification UI section**

In the edit view (line 170, inside `view === 'edit'`), add the reclassification section above the existing field grid. Replace the fragment's content:

```tsx
{view === 'edit' ? (
  <>
    <p className="mb-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
      Only fields you fill in or mark as "Clear" will be changed. All other fields remain unchanged.
    </p>

    {/* Reclassification section */}
    <div
      className="mb-6 pb-4 border-b"
      style={{ borderColor: 'var(--color-border)' }}
    >
      <div className="flex items-center gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
            Image Content
          </label>
          <select
            value={imageContentToggle}
            onChange={(e) => {
              const val = e.target.value as 'unchanged' | 'yes' | 'no';
              setImageContentToggle(val);
              if (val !== 'yes') {
                setContentType('');
                setReExtract(false);
              }
            }}
            className="input"
            style={{ height: '40px', minWidth: '140px' }}
          >
            <option value="unchanged">Unchanged</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>

        {imageContentToggle === 'yes' && (
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
              Content Type
            </label>
            <select
              value={contentType}
              onChange={(e) => setContentType(e.target.value)}
              className="input"
              style={{ height: '40px', minWidth: '160px' }}
            >
              <option value="">Select type...</option>
              {CONTENT_TYPES.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        )}
      </div>
    </div>

    {/* Existing field grid */}
    <div className="grid grid-cols-2 gap-x-6 gap-y-4">
      ...existing code...
    </div>
  </>
)
```

- [ ] **Step 3: Disable product_type field when Image Content is "Yes"**

In the `renderField` function, add a disabled check:

```typescript
const renderField = (key: string) => {
  const state = fieldStates[key];
  const isYear = key === 'publication_year';
  const isDisabledByReclassify = key === 'product_type' && imageContentToggle === 'yes';

  return (
    <div key={key} className="flex flex-col gap-1">
      <label className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
        {FIELD_LABELS[key]}
        {isDisabledByReclassify && (
          <span className="text-xs ml-1" style={{ color: 'var(--color-text-tertiary)' }}>
            (set by Content Type)
          </span>
        )}
      </label>
      <div className="flex items-center gap-2">
        <input
          type={isYear ? 'number' : 'text'}
          value={state.value}
          onChange={(e) => updateField(key, e.target.value)}
          disabled={state.clear || isDisabledByReclassify}
          placeholder={state.clear ? '(will be cleared)' : isDisabledByReclassify ? '(set by content type)' : ''}
          className="input flex-1"
          style={{
            height: '40px',
            opacity: (state.clear || isDisabledByReclassify) ? 0.5 : 1,
          }}
        />
        ...existing clear checkbox...
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Update Preview Changes button to require content_type when needed**

Update the disabled condition for the "Preview Changes" button:

```typescript
disabled={
  changedFields.length === 0 && imageContentToggle === 'unchanged'
  || (imageContentToggle === 'yes' && !contentType)
}
```

- [ ] **Step 5: Update preview view with reclassification info**

In the preview view section (after "Changes to apply:" heading), add reclassification info before the existing `changedFields.map`:

```tsx
{/* Reclassification info */}
{imageContentToggle === 'yes' && (
  <li className="text-sm font-medium" style={{ color: 'var(--color-accent)' }}>
    {selectedProducts.length} products → Image Content ({contentType})
  </li>
)}
{imageContentToggle === 'no' && (
  <li className="text-sm font-medium" style={{ color: 'var(--color-danger)' }}>
    {selectedProducts.length} products → Regular (extracted images will be deleted)
  </li>
)}
```

Add re-extract option in preview when setting to image content and some products already have images:

```tsx
{imageContentToggle === 'yes' && (() => {
  const alreadyExtracted = selectedProducts.filter(p => p.images_extracted);
  if (alreadyExtracted.length === 0) return null;
  return (
    <div className="mt-3 p-3 rounded-md" style={{
      backgroundColor: 'var(--color-surface-raised)',
      border: '1px solid var(--color-border)',
    }}>
      <label className="flex items-center gap-2 text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>
        <input
          type="checkbox"
          checked={reExtract}
          onChange={(e) => setReExtract(e.target.checked)}
        />
        {alreadyExtracted.length} products already have extracted images. Re-extract?
      </label>
    </div>
  );
})()}
```

- [ ] **Step 6: Update mutation to include reclassification fields**

In the `mutationFn`, after building the `fields` object from fieldStates, add:

```typescript
if (imageContentToggle === 'yes') {
  fields.is_image_content = true;
  fields.content_type = contentType;
  fields.re_extract = reExtract;
} else if (imageContentToggle === 'no') {
  fields.is_image_content = false;
}
```

- [ ] **Step 7: Add gallery query invalidation**

In the `onSuccess` callback, add:

```typescript
queryClient.invalidateQueries({ queryKey: ['gallery'] });
```

- [ ] **Step 8: Verify the frontend compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/BulkEditModal.tsx
git commit -m "feat: add Image Content toggle and Content Type dropdown to BulkEditModal"
```

---

## Chunk 4: Integration Verification

### Task 7: Full Test Suite and Manual Verification

- [ ] **Step 1: Run full backend test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS (including new reclassification tests)

- [ ] **Step 2: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Manual smoke test**

1. Start backend: `cd backend && python -m grimoire`
2. Start frontend: `cd frontend && npm run dev`
3. Select products in Library → Click "Edit Selected"
4. Verify Image Content toggle appears above field grid
5. Set to "Yes" → verify Content Type dropdown appears and product_type field is disabled
6. Select "Map" → Preview → verify message shows reclassification info
7. Apply → verify products update and appear in Gallery
8. Re-select → set Image Content to "No" → verify warning about image deletion in preview
9. Apply → verify products return to regular and images are cleaned up

- [ ] **Step 4: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: address integration issues from manual testing"
```
