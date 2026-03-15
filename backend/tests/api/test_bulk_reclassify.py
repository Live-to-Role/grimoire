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
        await set_content_type_tag(db, product.id, "Map")
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
        db.add(ProductTag(product_id=product.id, tag_id=seeded_tags["Map"].id, source="user"))
        await db.flush()

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
            content_type="Map",
        )
        assert req.is_image_content is False
        assert req.content_type == "Map"  # accepted but ignored by handler

    def test_is_image_content_true_with_product_type_uses_content_type(self):
        """Spec: product_type is ignored when is_image_content=True (content_type wins)."""
        from grimoire.api.routes.bulk import BulkUpdateRequest

        req = BulkUpdateRequest(
            product_ids=[1],
            is_image_content=True,
            content_type="Map",
            product_type="Adventure",
        )
        assert req.is_image_content is True
        assert req.content_type == "Map"

    def test_unchanged_omits_is_image_content(self):
        from grimoire.api.routes.bulk import BulkUpdateRequest

        req = BulkUpdateRequest(product_ids=[1], game_system="D&D 5e")
        assert "is_image_content" not in req.model_fields_set


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
            product_type="Adventure",
        )
        await bulk_update_products(db, req)
        await db.refresh(p)
        assert p.product_type == "Map"
