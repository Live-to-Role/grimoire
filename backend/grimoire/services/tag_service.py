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

BUILTIN_TAG_NAMES = {t["name"] for t in BUILTIN_TAGS}


async def seed_builtin_tags(db: AsyncSession) -> None:
    """Create built-in tags if they don't exist."""
    for tag_data in BUILTIN_TAGS:
        result = await db.execute(select(Tag).where(Tag.name == tag_data["name"]))
        existing = result.scalar_one_or_none()
        if not existing:
            tag = Tag(is_builtin=True, **tag_data)
            db.add(tag)
    await db.commit()


async def set_content_type_tag(
    db: AsyncSession, product_id: int, content_type: str
) -> None:
    """Remove existing auto content-type tags and set the new one.

    Only removes tags with source="auto" on builtin content_type tags.
    User-applied tags are preserved.
    """
    from grimoire.models import ProductTag

    await remove_content_type_tags(db, product_id)

    result = await db.execute(
        select(Tag).where(Tag.name == content_type, Tag.is_builtin == True)
    )
    tag = result.scalar_one()

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

    result = await db.execute(
        select(Tag.id).where(Tag.category == "content_type", Tag.is_builtin == True)
    )
    builtin_tag_ids = [row[0] for row in result.all()]

    if not builtin_tag_ids:
        return

    result = await db.execute(
        select(ProductTag).where(
            ProductTag.product_id == product_id,
            ProductTag.tag_id.in_(builtin_tag_ids),
            ProductTag.source == "auto",
        )
    )
    for pt in result.scalars().all():
        await db.delete(pt)
