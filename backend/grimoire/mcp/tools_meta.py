"""library_stats: counts and the search mode. Doubles as the health check."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.mcp.common import search_mode
from grimoire.models import MonsterEntry, Product
from grimoire.models.product import live_product_conditions
from grimoire.models.product_search_vector import ProductSearchVector


async def _count(db: AsyncSession, statement) -> int:
    return (await db.execute(statement)).scalar() or 0


async def library_stats(db: AsyncSession) -> dict:
    live = live_product_conditions()
    products = await _count(db, select(func.count(Product.id)).where(*live))
    extracted = await _count(
        db,
        select(func.count(Product.id)).where(*live, Product.text_extracted == True),  # noqa: E712
    )
    # Semantic search ranks over product_search_vectors (one averaged vector per
    # product), not over the chunk embeddings, so this is what it can find.
    embedded = await _count(
        db,
        select(func.count(func.distinct(ProductSearchVector.product_id)))
        .join(Product, Product.id == ProductSearchVector.product_id)
        .where(*live),
    )
    monsters = await _count(
        db,
        select(func.count(MonsterEntry.id)).where(MonsterEntry.review_status == "confirmed"),
    )
    mode, provider = await search_mode(db)
    return {
        "products": products,
        "text_extracted": extracted,
        "embedded": embedded,
        "confirmed_monsters": monsters,
        "search_mode": mode,
        "semantic_provider": provider,
    }
