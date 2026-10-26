"""Shared helpers for MCP tools: compact product rows, lookups, errors."""

import json
from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from grimoire.models import Product, ProductTag, Setting
from grimoire.models.product import live_product_conditions
from grimoire.services.classification.enum import CODEX_PRODUCT_TYPES, canonical_product_type

__all__ = [
    "ProductTypeFilter", "ToolError", "load_product", "product_summary", "product_type_filter",
    "search_mode", "json_list",
]

# Hard ceiling on characters of document text any single call returns.
MAX_CHARS = 20_000


# The product_type parameter's description, shared by every tool that filters
# on it. Built from the enum so it cannot drift; magazine is left out because
# every periodical is stored as zine (and "magazine" is mapped to it).
ProductTypeFilter = Annotated[str | None, Field(description=(
    "Filter by product type, ignoring case: "
    + ", ".join(t for t in CODEX_PRODUCT_TYPES if t != "magazine")
    + ". Common spellings (\"Rulebook\", \"Map\") are mapped. Image packs may carry "
    "free-text types such as Token, Portrait or Stock Art. An unknown type is an "
    "error that lists the library's types."
))]

# How many stored types an unknown-type error lists, most common first.
TYPES_LISTED = 30


async def product_type_filter(db: AsyncSession, value: str | None) -> str | None:
    """A caller's product_type, as the column actually stores it.

    The filters downstream are exact matches. The column holds the Codex enum
    plus free text the Product model keeps as written ("Token"), so the value
    is mapped with the model's own rule, then looked up among the stored
    types ignoring case. An unknown type is an error that lists the stored
    types: an empty result would read as "the library has none".
    """
    if value is None or not value.strip():
        return None
    value = value.strip()
    rows = (await db.execute(
        select(Product.product_type, func.count(Product.id))
        .where(*live_product_conditions(), Product.product_type.is_not(None))
        .group_by(Product.product_type)
        .order_by(func.count(Product.id).desc())
    )).all()
    stored: dict[str, str] = {}
    for product_type, _ in rows:
        stored.setdefault(product_type.lower(), product_type)
    for candidate in (canonical_product_type(value), value):
        if candidate.lower() in stored:
            return stored[candidate.lower()]
    listed = ", ".join(t for t, _ in rows[:TYPES_LISTED])
    raise ToolError(f"unknown product_type {value!r}; the library's types include: {listed}")


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
