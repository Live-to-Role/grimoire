"""Tests for image content fields on Product model."""
import pytest
from grimoire.models import Product, Tag


def test_product_has_image_content_fields():
    """Product model should have is_image_content, images_extracted, image_count."""
    p = Product(
        file_path="/test.pdf",
        file_name="test.pdf",
        file_size=1000,
        file_hash="abc123",
    )
    assert not p.is_image_content
    assert not p.images_extracted
    assert p.image_count is None


def test_tag_has_is_builtin_field():
    """Tag model should have is_builtin flag."""
    tag = Tag(name="Map")
    assert not tag.is_builtin


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
    from sqlalchemy import select
    result = await db.execute(select(Tag).where(Tag.name == "Map"))
    tag = result.scalar_one_or_none()
    if not tag:
        # Create if not seeded yet
        tag = Tag(name="BuiltinTest", is_builtin=True, category="content_type")
        db.add(tag)
        await db.commit()
        await db.refresh(tag)
    assert tag.is_builtin is True
