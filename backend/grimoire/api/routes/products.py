"""Product API endpoints."""

from datetime import datetime, UTC
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from grimoire.api.deps import DbSession, Pagination
from grimoire.config import settings
from grimoire.utils.security import validate_covers_path, validate_path_in_directory, PathTraversalError
from grimoire.models import Product, ProductTag, Tag
from grimoire.schemas.product import (
    ProductListResponse,
    ProductProcessRequest,
    ProductProcessResponse,
    ProductResponse,
    ProductUpdate,
    ProcessingStatus,
    RunStatus,
)
from grimoire.schemas.tag import TagResponse

router = APIRouter()


def product_to_response(product: Product) -> ProductResponse:
    """Convert a Product model to ProductResponse schema."""
    cover_url = None
    
    # For duplicates, use the original's cover if available
    if product.is_duplicate and product.duplicate_of_id:
        cover_url = f"/api/v1/products/{product.id}/cover"
    elif product.cover_extracted and product.cover_image_path:
        # Only set cover_url if the cover file actually exists
        if Path(product.cover_image_path).exists():
            cover_url = f"/api/v1/products/{product.id}/cover"

    # Build run status if any run tracking data exists
    run_status = None
    if product.run_status or product.run_rating or product.run_difficulty:
        run_status = RunStatus(
            status=product.run_status,
            rating=product.run_rating,
            difficulty=product.run_difficulty,
            completed_at=product.run_completed_at,
        )

    tags = []
    for pt in product.product_tags:
        tags.append(
            TagResponse(
                id=pt.tag.id,
                name=pt.tag.name,
                category=pt.tag.category,
                color=pt.tag.color,
                created_at=pt.tag.created_at,
                product_count=0,
            )
        )

    return ProductResponse(
        id=product.id,
        file_path=product.file_path,
        file_name=product.file_name,
        file_size=product.file_size,
        title=product.title,
        author=product.author,
        publisher=product.publisher,
        publication_year=product.publication_year,
        game_system=product.game_system,
        genre=product.genre,
        product_type=product.product_type,
        level_range_min=product.level_range_min,
        level_range_max=product.level_range_max,
        party_size_min=product.party_size_min,
        party_size_max=product.party_size_max,
        estimated_runtime=product.estimated_runtime,
        page_count=product.page_count,
        cover_url=cover_url,
        tags=tags,
        processing_status=ProcessingStatus(
            cover_extracted=product.cover_extracted,
            text_extracted=product.text_extracted,
            deep_indexed=product.deep_indexed,
            ai_identified=product.ai_identified,
        ),
        run_status=run_status,
        created_at=product.created_at,
        updated_at=product.updated_at,
        last_opened_at=product.last_opened_at,
    )


@router.get("", response_model=ProductListResponse)
async def list_products(
    db: DbSession,
    pagination: Pagination,
    sort: Literal["title", "created_at", "updated_at", "last_opened_at", "file_name"] = "title",
    order: Literal["asc", "desc"] = "asc",
    search: str | None = Query(None, description="Search in title and file name"),
    game_system: str | None = Query(None, description="Filter by game system"),
    genre: str | None = Query(None, description="Filter by genre"),
    product_type: str | None = Query(None, description="Filter by product type"),
    publisher: str | None = Query(None, description="Filter by publisher"),
    author: str | None = Query(None, description="Filter by author"),
    tags: str | None = Query(None, description="Comma-separated tag IDs"),
    collection: int | None = Query(None, description="Filter by collection ID"),
    has_cover: bool | None = Query(None, description="Filter by cover status"),
    publication_year_min: int | None = Query(None, description="Minimum publication year"),
    publication_year_max: int | None = Query(None, description="Maximum publication year"),
    level_min: int | None = Query(None, description="Minimum level (filters products with overlapping level range)"),
    level_max: int | None = Query(None, description="Maximum level (filters products with overlapping level range)"),
    party_size_min: int | None = Query(None, description="Minimum party size"),
    party_size_max: int | None = Query(None, description="Maximum party size"),
    estimated_runtime: str | None = Query(None, description="Filter by estimated runtime (partial match)"),
) -> ProductListResponse:
    """List products with filtering and pagination."""
    query = select(Product).options(selectinload(Product.product_tags).selectinload(ProductTag.tag))

    # Apply filters
    if search:
        search_term = f"%{search}%"
        query = query.where(
            (Product.title.ilike(search_term)) | (Product.file_name.ilike(search_term))
        )

    if game_system:
        if game_system == "Unknown":
            query = query.where(Product.game_system.is_(None))
        else:
            query = query.where(Product.game_system == game_system)

    if product_type:
        if product_type == "Unknown":
            query = query.where(Product.product_type.is_(None))
        else:
            query = query.where(Product.product_type == product_type)

    if genre:
        if genre == "Unknown":
            query = query.where(Product.genre.is_(None))
        else:
            query = query.where(Product.genre == genre)

    if publisher:
        if publisher == "Unknown":
            query = query.where(Product.publisher.is_(None))
        else:
            query = query.where(Product.publisher == publisher)

    if author:
        if author == "Unknown":
            query = query.where(Product.author.is_(None))
        else:
            query = query.where(Product.author == author)

    if has_cover is not None:
        query = query.where(Product.cover_extracted == has_cover)

    if tags:
        tag_ids = [int(t.strip()) for t in tags.split(",") if t.strip().isdigit()]
        if tag_ids:
            query = query.join(ProductTag).where(ProductTag.tag_id.in_(tag_ids))

    if collection:
        from grimoire.models import CollectionProduct

        query = query.join(CollectionProduct).where(CollectionProduct.collection_id == collection)

    # Publication year range filters
    if publication_year_min is not None:
        query = query.where(Product.publication_year >= publication_year_min)
    if publication_year_max is not None:
        query = query.where(Product.publication_year <= publication_year_max)

    # Level range filters (find products whose level range overlaps with the filter range)
    if level_min is not None:
        # Product's max level must be >= filter's min level (or product has no max set)
        query = query.where(
            (Product.level_range_max >= level_min) | (Product.level_range_max.is_(None))
        )
    if level_max is not None:
        # Product's min level must be <= filter's max level (or product has no min set)
        query = query.where(
            (Product.level_range_min <= level_max) | (Product.level_range_min.is_(None))
        )

    # Party size range filters
    if party_size_min is not None:
        query = query.where(
            (Product.party_size_max >= party_size_min) | (Product.party_size_max.is_(None))
        )
    if party_size_max is not None:
        query = query.where(
            (Product.party_size_min <= party_size_max) | (Product.party_size_min.is_(None))
        )

    # Estimated runtime filter (partial match)
    if estimated_runtime:
        query = query.where(Product.estimated_runtime.ilike(f"%{estimated_runtime}%"))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply sorting
    sort_column = getattr(Product, sort, Product.title)
    if order == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    # Apply pagination
    offset = (pagination.page - 1) * pagination.per_page
    query = query.offset(offset).limit(pagination.per_page)

    result = await db.execute(query)
    products = result.scalars().unique().all()

    pages = (total + pagination.per_page - 1) // pagination.per_page if total > 0 else 1

    return ProductListResponse(
        items=[product_to_response(p) for p in products],
        total=total,
        page=pagination.page,
        per_page=pagination.per_page,
        pages=pages,
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(db: DbSession, product_id: int) -> ProductResponse:
    """Get a single product by ID."""
    query = (
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
    )
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return product_to_response(product)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    db: DbSession,
    product_id: int,
    update_data: ProductUpdate,
    send_to_codex: bool = False,
) -> ProductResponse:
    """
    Update product metadata.
    
    Args:
        send_to_codex: If True, explicitly queue this product for Codex contribution
                       regardless of auto-contribute setting.
    """
    query = (
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
    )
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(product, field, value)

    product.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(product)

    # Queue for Codex contribution
    if send_to_codex:
        # User explicitly requested to send to Codex
        from grimoire.services.sync_service import queue_product_for_contribution
        await queue_product_for_contribution(db, product, submit_immediately=True)
    else:
        # Auto-queue edit if contribute is enabled in settings
        from grimoire.services.sync_service import queue_local_edit_for_sync
        await queue_local_edit_for_sync(db, product, update_dict)

    return product_to_response(product)


@router.delete("/{product_id}", status_code=204)
async def delete_product(db: DbSession, product_id: int) -> Response:
    """Delete a product from the library (does not delete the file)."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    await db.delete(product)
    await db.commit()

    return Response(status_code=204)


@router.get("/{product_id}/cover")
async def get_product_cover(db: DbSession, product_id: int) -> FileResponse:
    """Get the cover image for a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # For duplicates, get the original's cover
    if product.is_duplicate and product.duplicate_of_id:
        orig_query = select(Product).where(Product.id == product.duplicate_of_id)
        orig_result = await db.execute(orig_query)
        original = orig_result.scalar_one_or_none()
        if original and original.cover_extracted and original.cover_image_path:
            product = original

    if not product.cover_extracted or not product.cover_image_path:
        raise HTTPException(status_code=404, detail="Cover not available")

    cover_path = Path(product.cover_image_path)
    
    # Validate path is within allowed directory
    try:
        validate_covers_path(cover_path)
    except PathTraversalError:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not cover_path.exists():
        raise HTTPException(status_code=404, detail="Cover file not found")

    return FileResponse(
        cover_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{product_id}/pdf")
async def get_product_pdf(db: DbSession, product_id: int) -> FileResponse:
    """Get the PDF file for viewing."""
    from grimoire.models import WatchedFolder
    
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if product.is_missing:
        raise HTTPException(
            status_code=404, 
            detail="PDF file is missing from disk. The file may have been moved or deleted."
        )

    pdf_path = Path(product.file_path)
    
    # Validate path is within the product's watched folder
    if product.watched_folder_id:
        folder_result = await db.execute(
            select(WatchedFolder).where(WatchedFolder.id == product.watched_folder_id)
        )
        watched_folder = folder_result.scalar_one_or_none()
        if watched_folder:
            try:
                validate_path_in_directory(pdf_path, watched_folder.path)
            except PathTraversalError:
                raise HTTPException(status_code=403, detail="Access denied")
    
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")

    # Update last opened timestamp (non-blocking - don't fail if DB is locked)
    try:
        product.last_opened_at = datetime.now(UTC)
        await db.commit()
    except Exception:
        await db.rollback()  # Don't let failed update block PDF serving

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{product.file_name}"',
            "Accept-Ranges": "bytes",
        },
    )


@router.post("/{product_id}/process", response_model=ProductProcessResponse)
async def process_product(
    db: DbSession, product_id: int, request: ProductProcessRequest
) -> ProductProcessResponse:
    """Queue processing tasks for a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    from grimoire.models import ProcessingQueue

    queue_ids = []
    for task in request.tasks:
        queue_item = ProcessingQueue(
            product_id=product_id,
            task_type=task,
            priority=5,
            status="pending",
        )
        db.add(queue_item)
        await db.flush()
        queue_ids.append(queue_item.id)

    await db.commit()

    return ProductProcessResponse(
        queue_ids=queue_ids,
        message=f"Queued {len(queue_ids)} task(s) for processing",
    )


@router.get("/{product_id}/text")
async def get_product_text(db: DbSession, product_id: int) -> dict:
    """Get the extracted text for a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    from grimoire.services.processor import get_extracted_text

    text = get_extracted_text(product)
    if text is None:
        raise HTTPException(status_code=404, detail="Text not extracted yet")

    return {
        "product_id": product_id,
        "markdown": text,
        "char_count": len(text),
    }


@router.post("/{product_id}/extract")
async def extract_product_text(
    db: DbSession,
    product_id: int,
    use_marker: bool = Query(False, description="Use Marker for better quality (slower)"),
) -> dict:
    """Extract text from a product's PDF."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    from grimoire.services.processor import process_text_extraction_sync

    success = process_text_extraction_sync(product, use_marker=use_marker)

    if not success:
        raise HTTPException(status_code=500, detail="Text extraction failed")

    await db.commit()

    return {
        "product_id": product_id,
        "text_extracted": True,
        "message": "Text extraction completed",
    }


@router.post("/{product_id}/tags", status_code=201)
async def add_tag_to_product(db: DbSession, product_id: int, tag_id: int) -> dict:
    """Add a tag to a product."""
    product_query = select(Product).where(Product.id == product_id)
    product_result = await db.execute(product_query)
    product = product_result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    tag_query = select(Tag).where(Tag.id == tag_id)
    tag_result = await db.execute(tag_query)
    tag = tag_result.scalar_one_or_none()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    existing = await db.execute(
        select(ProductTag).where(
            ProductTag.product_id == product_id, ProductTag.tag_id == tag_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tag already added to product")

    product_tag = ProductTag(product_id=product_id, tag_id=tag_id, source="user")
    db.add(product_tag)
    await db.commit()

    return {"message": "Tag added to product"}


@router.delete("/{product_id}/tags/{tag_id}", status_code=204)
async def remove_tag_from_product(db: DbSession, product_id: int, tag_id: int) -> Response:
    """Remove a tag from a product."""
    query = select(ProductTag).where(
        ProductTag.product_id == product_id, ProductTag.tag_id == tag_id
    )
    result = await db.execute(query)
    product_tag = result.scalar_one_or_none()

    if not product_tag:
        raise HTTPException(status_code=404, detail="Tag not found on product")

    await db.delete(product_tag)
    await db.commit()

    return Response(status_code=204)


@router.get("/{product_id}/collections")
async def get_product_collections(db: DbSession, product_id: int) -> dict:
    """Get the collections a product belongs to."""
    from grimoire.models import CollectionProduct
    
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    collections_query = select(CollectionProduct.collection_id).where(
        CollectionProduct.product_id == product_id
    )
    collections_result = await db.execute(collections_query)
    collection_ids = [row[0] for row in collections_result.fetchall()]

    return {"collection_ids": collection_ids}


@router.put("/{product_id}/run-status")
async def update_run_status(
    db: DbSession,
    product_id: int,
    run_status: str | None = Query(None, description="Run status: want_to_run, running, completed"),
    run_rating: int | None = Query(None, ge=1, le=5, description="Rating 1-5"),
    run_difficulty: str | None = Query(None, description="Difficulty: easier, as_written, harder"),
) -> dict:
    """Update run tracking status for a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Validate run_status
    valid_statuses = {"want_to_run", "running", "completed", None}
    if run_status is not None and run_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid run_status. Must be one of: {valid_statuses}")

    # Validate run_difficulty
    valid_difficulties = {"easier", "as_written", "harder", None}
    if run_difficulty is not None and run_difficulty not in valid_difficulties:
        raise HTTPException(status_code=400, detail=f"Invalid run_difficulty. Must be one of: {valid_difficulties}")

    # Update fields
    if run_status is not None:
        product.run_status = run_status if run_status else None
        # Set completed timestamp when marking as completed
        if run_status == "completed" and not product.run_completed_at:
            product.run_completed_at = datetime.now(UTC)
        elif run_status != "completed":
            product.run_completed_at = None

    if run_rating is not None:
        product.run_rating = run_rating

    if run_difficulty is not None:
        product.run_difficulty = run_difficulty if run_difficulty else None

    await db.commit()

    return {
        "id": product.id,
        "run_status": product.run_status,
        "run_rating": product.run_rating,
        "run_difficulty": product.run_difficulty,
        "run_completed_at": product.run_completed_at.isoformat() if product.run_completed_at else None,
    }


@router.delete("/{product_id}/run-status")
async def clear_run_status(
    db: DbSession,
    product_id: int,
) -> dict:
    """Clear all run tracking data for a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.run_status = None
    product.run_rating = None
    product.run_difficulty = None
    product.run_completed_at = None

    await db.commit()

    return {"id": product.id, "cleared": True}
