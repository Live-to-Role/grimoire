"""Bulk operations API endpoints."""

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from grimoire.api.deps import DbSession
from grimoire.models import Product, Tag, ProductTag, Collection, CollectionProduct

router = APIRouter()


class BulkTagRequest(BaseModel):
    """Request to add/remove tags from multiple products."""

    product_ids: list[int] = Field(..., min_length=1)
    tag_ids: list[int] = Field(..., min_length=1)


class BulkCollectionRequest(BaseModel):
    """Request to add/remove products from a collection."""

    product_ids: list[int] = Field(..., min_length=1)
    collection_id: int


class BulkUpdateRequest(BaseModel):
    """Request to update fields on multiple products."""

    product_ids: list[int] = Field(..., min_length=1)
    game_system: str | None = None
    product_type: str | None = None
    publisher: str | None = None
    publication_year: int | None = None


class BulkDeleteRequest(BaseModel):
    """Request to delete multiple products."""

    product_ids: list[int] = Field(..., min_length=1)


class BulkResponse(BaseModel):
    """Response for bulk operations."""

    message: str
    affected: int
    errors: list[str] = []


@router.post("/tags/add", response_model=BulkResponse)
async def bulk_add_tags(db: DbSession, request: BulkTagRequest) -> BulkResponse:
    """Add tags to multiple products."""
    tags_query = select(Tag).where(Tag.id.in_(request.tag_ids))
    tags_result = await db.execute(tags_query)
    tags = list(tags_result.scalars().all())

    if len(tags) != len(request.tag_ids):
        found_ids = {t.id for t in tags}
        missing = [tid for tid in request.tag_ids if tid not in found_ids]
        raise HTTPException(status_code=404, detail=f"Tags not found: {missing}")

    products_query = select(Product).where(Product.id.in_(request.product_ids))
    products_result = await db.execute(products_query)
    products = list(products_result.scalars().all())

    affected = 0
    errors = []

    for product in products:
        for tag in tags:
            existing = await db.execute(
                select(ProductTag).where(
                    ProductTag.product_id == product.id,
                    ProductTag.tag_id == tag.id,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(ProductTag(product_id=product.id, tag_id=tag.id, source="bulk"))
                affected += 1

    await db.commit()

    return BulkResponse(
        message=f"Added tags to products",
        affected=affected,
        errors=errors,
    )


@router.post("/tags/remove", response_model=BulkResponse)
async def bulk_remove_tags(db: DbSession, request: BulkTagRequest) -> BulkResponse:
    """Remove tags from multiple products."""
    affected = 0

    for product_id in request.product_ids:
        for tag_id in request.tag_ids:
            result = await db.execute(
                select(ProductTag).where(
                    ProductTag.product_id == product_id,
                    ProductTag.tag_id == tag_id,
                )
            )
            product_tag = result.scalar_one_or_none()
            if product_tag:
                await db.delete(product_tag)
                affected += 1

    await db.commit()

    return BulkResponse(
        message=f"Removed tags from products",
        affected=affected,
    )


@router.post("/collection/add", response_model=BulkResponse)
async def bulk_add_to_collection(db: DbSession, request: BulkCollectionRequest) -> BulkResponse:
    """Add multiple products to a collection."""
    collection_query = select(Collection).where(Collection.id == request.collection_id)
    collection_result = await db.execute(collection_query)
    collection = collection_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    affected = 0

    for product_id in request.product_ids:
        existing = await db.execute(
            select(CollectionProduct).where(
                CollectionProduct.collection_id == request.collection_id,
                CollectionProduct.product_id == product_id,
            )
        )
        if not existing.scalar_one_or_none():
            db.add(CollectionProduct(
                collection_id=request.collection_id,
                product_id=product_id,
            ))
            affected += 1

    await db.commit()

    return BulkResponse(
        message=f"Added products to collection '{collection.name}'",
        affected=affected,
    )


@router.post("/collection/remove", response_model=BulkResponse)
async def bulk_remove_from_collection(db: DbSession, request: BulkCollectionRequest) -> BulkResponse:
    """Remove multiple products from a collection."""
    affected = 0

    for product_id in request.product_ids:
        result = await db.execute(
            select(CollectionProduct).where(
                CollectionProduct.collection_id == request.collection_id,
                CollectionProduct.product_id == product_id,
            )
        )
        cp = result.scalar_one_or_none()
        if cp:
            await db.delete(cp)
            affected += 1

    await db.commit()

    return BulkResponse(
        message=f"Removed products from collection",
        affected=affected,
    )


@router.post("/update", response_model=BulkResponse)
async def bulk_update_products(db: DbSession, request: BulkUpdateRequest) -> BulkResponse:
    """Update fields on multiple products."""
    products_query = select(Product).where(Product.id.in_(request.product_ids))
    products_result = await db.execute(products_query)
    products = list(products_result.scalars().all())

    affected = 0

    for product in products:
        updated = False
        if request.game_system is not None:
            product.game_system = request.game_system
            updated = True
        if request.product_type is not None:
            product.product_type = request.product_type
            updated = True
        if request.publisher is not None:
            product.publisher = request.publisher
            updated = True
        if request.publication_year is not None:
            product.publication_year = request.publication_year
            updated = True

        if updated:
            affected += 1

    await db.commit()

    return BulkResponse(
        message=f"Updated products",
        affected=affected,
    )


@router.post("/delete", response_model=BulkResponse)
async def bulk_delete_products(db: DbSession, request: BulkDeleteRequest) -> BulkResponse:
    """Delete multiple products."""
    products_query = select(Product).where(Product.id.in_(request.product_ids))
    products_result = await db.execute(products_query)
    products = list(products_result.scalars().all())

    affected = 0

    for product in products:
        await db.delete(product)
        affected += 1

    await db.commit()

    return BulkResponse(
        message=f"Deleted products",
        affected=affected,
    )


@router.post("/extract", response_model=BulkResponse)
async def bulk_extract_text(
    db: DbSession,
    product_ids: list[int],
    use_marker: bool = Query(False, description="Use Marker for better quality"),
) -> BulkResponse:
    """Extract text from specific products."""
    from grimoire.services.processor import process_text_extraction_sync

    products_query = select(Product).where(Product.id.in_(product_ids))
    products_result = await db.execute(products_query)
    products = list(products_result.scalars().all())

    affected = 0
    errors = []

    for product in products:
        try:
            if process_text_extraction_sync(product, use_marker=use_marker):
                affected += 1
            else:
                errors.append(f"Failed to extract: {product.file_name}")
        except Exception as e:
            errors.append(f"{product.file_name}: {str(e)}")

    await db.commit()

    return BulkResponse(
        message=f"Text extraction completed",
        affected=affected,
        errors=errors,
    )
