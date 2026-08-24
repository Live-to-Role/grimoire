"""Gallery API endpoint - aggregates image-content products."""

from datetime import datetime, UTC

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from grimoire.api.deps import DbSession
from grimoire.models import CollectionProduct, Product, ProductTag, Tag

router = APIRouter()


@router.get("")
async def list_gallery_products(
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    tag_id: int | None = Query(None, description="Filter by tag ID"),
    collection_id: int | None = Query(None, description="Filter by collection ID"),
    sort: str = Query("created_at", description="Sort by: created_at, title, image_count"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    search: str | None = Query(None, description="Search by title or filename"),
    needs_review: bool = Query(
        True,
        description="Only products no human has judged yet. On by default so the "
                    "review backlog visibly shrinks as it is worked through.",
    ),
):
    """List image-content products for the gallery view."""
    conditions = [Product.is_image_content == True]

    if needs_review:
        conditions.append(Product.classification_reviewed_at.is_(None))

    if tag_id:
        conditions.append(
            Product.id.in_(
                select(ProductTag.product_id).where(ProductTag.tag_id == tag_id)
            )
        )

    if collection_id:
        conditions.append(
            Product.id.in_(
                select(CollectionProduct.product_id).where(
                    CollectionProduct.collection_id == collection_id
                )
            )
        )

    if search:
        search_term = f"%{search}%"
        conditions.append(
            (Product.title.ilike(search_term)) | (Product.file_name.ilike(search_term))
        )

    # Count total
    count_query = select(func.count()).select_from(Product).where(*conditions)
    total = (await db.execute(count_query)).scalar() or 0

    # Sort
    sort_column = {
        "created_at": Product.created_at,
        "title": Product.title,
        "image_count": Product.image_count,
    }.get(sort, Product.created_at)

    order_func = sort_column.desc() if order == "desc" else sort_column.asc()

    # Query
    query = (
        select(Product)
        .where(*conditions)
        .order_by(order_func)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(query)
    products = result.scalars().all()

    # Get tags for each product
    product_ids = [p.id for p in products]
    if product_ids:
        tags_query = (
            select(ProductTag.product_id, Tag.id, Tag.name, Tag.color, Tag.is_builtin)
            .join(Tag, ProductTag.tag_id == Tag.id)
            .where(ProductTag.product_id.in_(product_ids))
        )
        tags_result = await db.execute(tags_query)
        product_tags = {}
        for row in tags_result:
            pid = row[0]
            if pid not in product_tags:
                product_tags[pid] = []
            product_tags[pid].append({
                "id": row[1], "name": row[2], "color": row[3], "is_builtin": row[4]
            })
    else:
        product_tags = {}

    items = []
    for p in products:
        items.append({
            "id": p.id,
            "title": p.title or p.file_name,
            "file_name": p.file_name,
            "product_type": p.product_type,
            "image_count": p.image_count or 0,
            "images_extracted": p.images_extracted,
            "cover_extracted": p.cover_extracted,
            "page_count": p.page_count,
            "publisher": p.publisher,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "classification_reviewed_at": (
                p.classification_reviewed_at.isoformat()
                if p.classification_reviewed_at else None
            ),
            "tags": product_tags.get(p.id, []),
        })

    # The GLOBAL backlog: every unreviewed image-content product, deliberately
    # ignoring tag/collection/search. It is the number being burned down, not a
    # count of what is on screen - so filtering by tag shows a count that does
    # not match the grid, and that is intended.
    needs_review_total = (await db.execute(
        select(func.count()).select_from(Product).where(
            Product.is_image_content == True,
            Product.classification_reviewed_at.is_(None),
        )
    )).scalar_one()

    return {
        "items": items,
        "total": total,
        "needs_review_total": needs_review_total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


class ConfirmImagesRequest(BaseModel):
    """Products the user has confirmed really are image content."""
    product_ids: list[int]


@router.post("/confirm-images")
async def confirm_images(db: DbSession, request: ConfirmImagesRequest) -> dict:
    """Record that a human judged these products correctly classified.

    Deliberately changes nothing but the timestamp. Its whole purpose is to
    remove a correctly-classified product from the needs-review queue - the
    counterpart to marking a scan, and the reason that queue can ever empty.
    """
    result = await db.execute(
        select(Product).where(Product.id.in_(request.product_ids))
    )
    products = list(result.scalars().all())

    now = datetime.now(UTC)
    for product in products:
        product.classification_reviewed_at = now

    await db.commit()
    return {"reviewed": len(products)}
