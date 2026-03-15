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
