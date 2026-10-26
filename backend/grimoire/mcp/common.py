"""Shared helpers for MCP tools: compact product rows, lookups, errors."""

import json

from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from grimoire.models import Product, ProductTag, Setting
from grimoire.services.classification.enum import canonical_product_type

__all__ = [
    "ToolError", "load_product", "product_summary", "product_type_filter", "search_mode", "json_list",
]

# Hard ceiling on characters of document text any single call returns.
MAX_CHARS = 20_000


def product_type_filter(value: str | None) -> str | None:
    """A caller's product_type, spelled the way the column stores it.

    The filters are exact matches and the column holds the Codex enum, so an
    assistant's "Rulebook" or "Map" would otherwise match nothing. Same rule
    the Product model applies on write.
    """
    if value is None or not value.strip():
        return None
    return canonical_product_type(value.strip())


def product_summary(product: Product) -> dict:
    """The compact row every tool uses for a product. Never the full response."""
    return {
        "product_id": product.id,
        "title": product.title or product.file_name,
        "author": product.author,
        "publisher": product.publisher,
        "game_system": product.game_system,
        "product_type": product.product_type,
        "genre": product.genre,
        "setting": product.setting,
        "level_min": product.level_range_min,
        "level_max": product.level_range_max,
        "page_count": product.page_count,
        "publication_year": product.publication_year,
        "text_extracted": bool(product.text_extracted),
    }


async def load_product(db: AsyncSession, product_id: int, *, with_tags: bool = False) -> Product:
    query = select(Product).where(Product.id == product_id)
    if with_tags:
        query = query.options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
    product = (await db.execute(query)).scalar_one_or_none()
    if product is None:
        raise ToolError(f"Product {product_id} not found")
    return product


async def search_mode(db: AsyncSession) -> tuple[str, str]:
    """``("hybrid" | "keyword_only", provider)`` from the Settings page's choice.

    Mirrors the guard on ``POST /semantic/search``: with no provider the HTTP
    route refuses, but a tool should still answer, just in keyword mode.
    """
    result = await db.execute(select(Setting).where(Setting.key == "semantic_search_provider"))
    setting = result.scalar_one_or_none()
    provider = "none"
    if setting is not None:
        try:
            provider = json.loads(setting.value) or "none"
        except ValueError:
            provider = "none"
    return ("keyword_only" if provider == "none" else "hybrid", provider)


def json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return value if isinstance(value, list) else []
