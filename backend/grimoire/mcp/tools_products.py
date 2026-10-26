"""get_product, list_products, get_page, get_text."""

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.mcp.common import MAX_CHARS, ToolError, json_list, load_product, product_summary
from grimoire.models import Collection, CollectionProduct, Product, ProductTag, Tag
from grimoire.models.product import live_product_conditions

MAX_LIST = 100
MAX_CONTEXT_PAGES = 3


def _no_text(product: Product) -> ToolError:
    return ToolError(
        f"Product {product.id} has no extracted text yet. Ask the user to run "
        "text extraction for it in Grimoire."
    )


# The extraction JSON of a long book runs to tens of megabytes. Parsing it on
# the event loop stalls every request in flight, and an agent fans these calls
# out, so the reads go to a worker thread.
async def _read_pages(product: Product) -> list[dict] | None:
    from grimoire.services import processor

    return await asyncio.to_thread(processor.get_extracted_pages, product)


async def _read_text(product: Product) -> str | None:
    from grimoire.services import processor

    return await asyncio.to_thread(processor.get_extracted_text, product)


async def get_product(db: AsyncSession, *, product_id: int) -> dict:
    product = await load_product(db, product_id, with_tags=True)
    collections = await db.execute(
        select(Collection.id, Collection.name)
        .join(CollectionProduct, CollectionProduct.collection_id == Collection.id)
        .where(CollectionProduct.product_id == product.id)
        .order_by(Collection.name)
    )
    out = product_summary(product)
    out.update(
        {
            "description": product.description,
            "series": product.series,
            "series_order": product.series_order,
            "themes": json_list(product.themes),
            "isbn": product.isbn,
            "dtrpg_url": product.dtrpg_url,
            "file_name": product.file_name,
            "tags": sorted(pt.tag.name for pt in product.product_tags),
            "collections": [{"id": cid, "name": name} for cid, name in collections],
            "has_page_anchors": bool(
                product.text_extracted and await _read_pages(product) is not None
            ),
            "run_status": product.run_status,
            "is_duplicate": bool(product.is_duplicate),
        }
    )
    return out


async def list_products(
    db: AsyncSession,
    *,
    query: str | None = None,
    game_system: str | None = None,
    product_type: str | None = None,
    publisher: str | None = None,
    tag: str | None = None,
    collection_id: int | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    limit = max(1, min(int(limit), MAX_LIST))
    offset = max(0, int(offset))
    conditions = list(live_product_conditions())
    if query and query.strip():
        like = f"%{query.strip()}%"
        conditions.append(Product.title.ilike(like) | Product.file_name.ilike(like))
    if game_system:
        conditions.append(Product.game_system == game_system)
    if product_type:
        conditions.append(Product.product_type == product_type)
    if publisher:
        conditions.append(Product.publisher == publisher)
    if tag and tag.strip():
        tagged = (
            select(ProductTag.product_id)
            .join(Tag, Tag.id == ProductTag.tag_id)
            .where(func.lower(Tag.name) == tag.strip().lower())
        )
        conditions.append(Product.id.in_(tagged))
    if collection_id is not None:
        member = select(CollectionProduct.product_id).where(
            CollectionProduct.collection_id == collection_id
        )
        conditions.append(Product.id.in_(member))

    total = (await db.execute(select(func.count(Product.id)).where(*conditions))).scalar() or 0
    rows = await db.execute(
        select(Product)
        .where(*conditions)
        .order_by(Product.title, Product.file_name)
        .offset(offset)
        .limit(limit)
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": [product_summary(p) for p in rows.scalars().all()],
    }


async def _pages_or_error(product: Product) -> list[dict]:
    if not product.text_extracted:
        raise _no_text(product)
    pages = await _read_pages(product)
    if pages is not None:
        return pages
    if await _read_text(product) is None:
        raise ToolError(
            f"Product {product.id} is marked as extracted but its text file is missing. "
            "Ask the user to re-run text extraction for it."
        )
    raise ToolError(
        f"Product {product.id} was extracted before page anchors existed, so pages "
        "cannot be addressed. Ask the user to re-extract its text, or use get_text."
    )


async def get_page(
    db: AsyncSession, *, product_id: int, page: int, context_pages: int = 0
) -> dict:
    product = await load_product(db, product_id)
    pages = await _pages_or_error(product)
    by_number = {int(p["page"]): p.get("markdown") or "" for p in pages}
    # Page numbers are not contiguous: some extractors emit a marker only for
    # pages that had text, so a blank or image-only page is simply absent.
    count = max(product.page_count or 0, max(by_number, default=0))
    if page < 1 or page > count:
        raise ToolError(f"Page {page} is out of range: product {product_id} has {count} pages")
    if page not in by_number:
        raise ToolError(
            f"Page {page} of product {product_id} has no extracted text (a blank or "
            "image-only page). Neighbouring pages may; try context_pages."
        )

    context = max(0, min(int(context_pages), MAX_CONTEXT_PAGES))
    wanted = [n for n in range(page - context, page + context + 1) if n in by_number]

    budget = MAX_CHARS
    out_pages: list[dict] = []
    truncated = False
    for number in wanted:
        text = by_number[number]
        if len(text) > budget:
            text = text[:budget]
            truncated = True
        out_pages.append({"page": number, "markdown": text})
        budget -= len(text)
        if budget <= 0:
            if number != wanted[-1]:
                truncated = True
            break

    return {
        "product_id": product.id,
        "title": product.title or product.file_name,
        "page": page,
        "page_count": count,
        "pages": out_pages,
        "truncated": truncated,
    }


async def get_text(
    db: AsyncSession, *, product_id: int, offset: int = 0, max_chars: int = 8000
) -> dict:
    product = await load_product(db, product_id)
    if not product.text_extracted:
        raise _no_text(product)
    text = await _read_text(product)
    if text is None:
        raise ToolError(
            f"Product {product.id} is marked as extracted but its text file is missing. "
            "Ask the user to re-run text extraction for it."
        )

    offset = max(0, int(offset))
    max_chars = max(1, min(int(max_chars), MAX_CHARS))
    window = text[offset : offset + max_chars]
    end = offset + len(window)
    return {
        "product_id": product.id,
        "title": product.title or product.file_name,
        "offset": offset,
        "text": window,
        "total_chars": len(text),
        "next_offset": end if end < len(text) else None,
    }
