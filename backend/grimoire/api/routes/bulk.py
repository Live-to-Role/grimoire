"""Bulk operations API endpoints."""

import asyncio
import logging
import shutil

from pydantic import BaseModel, Field, model_validator
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from grimoire.api.deps import DbSession
from grimoire.config import settings
from grimoire.models import Product, Tag, ProductTag, Collection, CollectionProduct, ProcessingQueue

logger = logging.getLogger(__name__)

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
    """Request to update fields on multiple products.

    Fields set to a string value will be applied.
    Fields set to empty string "" will clear the value (set to None).
    Fields not included in the request are left unchanged.
    """

    product_ids: list[int] = Field(..., min_length=1)
    game_system: str | None = None
    product_type: str | None = None
    publisher: str | None = None
    author: str | None = None
    genre: str | None = None
    publication_year: int | None = None
    setting: str | None = None
    series: str | None = None
    estimated_runtime: str | None = None
    format: str | None = None

    # Reclassification fields
    is_image_content: bool | None = None
    content_type: str | None = None
    re_extract: bool = False

    @model_validator(mode="after")
    def validate_reclassification(self) -> "BulkUpdateRequest":
        if self.is_image_content is True:
            if not self.content_type:
                raise ValueError("content_type is required when is_image_content is True")
            from grimoire.services.tag_service import BUILTIN_TAG_NAMES
            if self.content_type not in BUILTIN_TAG_NAMES:
                raise ValueError(
                    f"content_type must be one of: {', '.join(sorted(BUILTIN_TAG_NAMES))}"
                )
        return self


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
    filter_fields_updated = False

    # Fields that trigger filter cache invalidation
    filter_relevant = {"game_system", "product_type", "publisher", "author", "genre"}

    # All updatable string fields
    string_fields = [
        "game_system", "product_type", "publisher", "author", "genre",
        "setting", "series", "estimated_runtime", "format",
    ]

    # Only update fields that were explicitly included in the request
    provided_fields = request.model_fields_set - {"product_ids"}

    if not provided_fields:
        return BulkResponse(message="No fields to update", affected=0)

    for product in products:
        updated = False

        for field in string_fields:
            if field in provided_fields:
                value = getattr(request, field)
                # Empty string means "clear the field"
                setattr(product, field, value if value != "" else None)
                updated = True
                if field in filter_relevant:
                    filter_fields_updated = True

        if "publication_year" in provided_fields:
            product.publication_year = request.publication_year
            updated = True

        if updated:
            affected += 1

    # Handle reclassification
    queued_count = 0

    if "is_image_content" in provided_fields and request.is_image_content is True:
        from grimoire.services.tag_service import set_content_type_tag

        for product in products:
            product.is_image_content = True
            product.product_type = request.content_type
            await set_content_type_tag(db, product.id, request.content_type)

            should_extract = not product.images_extracted or request.re_extract
            if should_extract:
                existing_task = await db.execute(
                    select(ProcessingQueue).where(
                        ProcessingQueue.product_id == product.id,
                        ProcessingQueue.task_type == "extract_images",
                        ProcessingQueue.status.in_(["pending", "processing"]),
                    )
                )
                if not existing_task.scalar_one_or_none():
                    db.add(ProcessingQueue(
                        product_id=product.id,
                        task_type="extract_images",
                        priority=2,
                        status="pending",
                    ))
                    queued_count += 1

        affected = len(products)
        filter_fields_updated = True

    elif "is_image_content" in provided_fields and request.is_image_content is False:
        # ⚠️ No local `import ProcessingQueue` here. It is imported at module
        # level (:14) and used by the branch above; re-importing it inside this
        # function makes it local to the whole function, so that earlier branch
        # dies with UnboundLocalError before ever reaching this one.
        from datetime import datetime, UTC

        from grimoire.services.processor import has_usable_text
        from grimoire.services.tag_service import remove_content_type_tags

        for product in products:
            # What the user asserts is "this is not a collection of images".
            # Whether it also needs OCR is a fact the database already knows,
            # so it is inferred rather than asked: of the 1,711 products the
            # image flag blocks, only 156 have no text at all. Treating every
            # un-flag as a scan would set is_scanned falsely on the other
            # 1,555 and queue that many needless OCR passes.
            needs_ocr = not has_usable_text(product)

            product.is_image_content = False
            product.product_type = None
            product.images_extracted = False
            product.image_count = None
            product.classification_reviewed_at = datetime.now(UTC)

            if needs_ocr:
                # The point of un-flagging one of these is to get the text.
                # This never queued anything, so the action deleted the images
                # and gained nothing.
                product.is_scanned = True
                db.add(ProcessingQueue(
                    product_id=product.id,
                    task_type="ocr_text",
                    priority=3,
                    status="pending",
                ))

            await remove_content_type_tags(db, product.id)

        affected = len(products)
        filter_fields_updated = True

    # Commit
    committed = False

    if "is_image_content" in provided_fields and request.is_image_content is False:
        await db.commit()
        committed = True

        for product in products:
            image_dir = settings.data_dir / "images" / str(product.id)
            if image_dir.exists():
                try:
                    shutil.rmtree(image_dir)
                except OSError as e:
                    logger.warning("Failed to delete image dir %s: %s", image_dir, e)

    if not committed:
        await db.commit()

    # Invalidate filter cache if filter-relevant fields were updated
    if filter_fields_updated:
        from grimoire.services.cache_service import get_cache_service
        cache = await get_cache_service()
        await cache.invalidate_filter_options()

    message = "Updated products"
    if queued_count > 0:
        message = f"Updated {affected} products. Queued {queued_count} for image extraction."

    return BulkResponse(
        message=message,
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
    
    # Invalidate filter cache since products were deleted
    if affected > 0:
        from grimoire.services.cache_service import get_cache_service
        cache = await get_cache_service()
        await cache.invalidate_filter_options()

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
            # Offload the CPU-heavy sync extraction (layout mode / OCR) to a
            # thread so it never blocks the event loop / other HTTP requests.
            if await asyncio.to_thread(
                process_text_extraction_sync, product, use_marker=use_marker
            ):
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
