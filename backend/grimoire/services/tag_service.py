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
