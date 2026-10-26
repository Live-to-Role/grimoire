"""library_stats: counts and the search mode. Doubles as the health check."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.mcp.common import search_mode
from grimoire.models import MonsterEntry, Product
from grimoire.models.product_search_vector import ProductSearchVector

_LIVE = (
    Product.is_duplicate == False,  # noqa: E712 - SQLAlchemy comparison
    Product.is_missing == False,  # noqa: E712
    Product.is_superseded == False,  # noqa: E712
)


async def _count(db: AsyncSession, statement) -> int:
    return (await db.execute(statement)).scalar() or 0


async def library_stats(db: AsyncSession) -> dict:
    products = await _count(db, select(func.count(Product.id)).where(*_LIVE))
    extracted = await _count(
        db,
        select(func.count(Product.id)).where(*_LIVE, Product.text_extracted == True),  # noqa: E712
    )
    # Semantic search ranks over product_search_vectors (one averaged vector per
    # product), not over the chunk embeddings, so this is what it can find.
    embedded = await _count(
        db,
        select(func.count(func.distinct(ProductSearchVector.product_id)))
        .join(Product, Product.id == ProductSearchVector.product_id)
        .where(*_LIVE),
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
