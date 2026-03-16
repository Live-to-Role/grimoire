"""Product API endpoints."""

import asyncio
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from grimoire.api.deps import DbSession, Pagination
from grimoire.config import settings
from grimoire.utils.security import validate_covers_path, validate_path_in_directory, PathTraversalError
from grimoire.models import Product, ProductTag, Tag
from grimoire.services.fts_service import check_fts_available
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
        description=product.description,
        publication_year=product.publication_year,
        game_system=product.game_system,
        genre=product.genre,
        product_type=product.product_type,
        setting=product.setting,
        level_range_min=product.level_range_min,
        level_range_max=product.level_range_max,
        party_size_min=product.party_size_min,
        party_size_max=product.party_size_max,
        estimated_runtime=product.estimated_runtime,
        series=product.series,
        series_order=product.series_order,
        format=product.format,
        isbn=product.isbn,
        msrp=product.msrp,
        dtrpg_url=product.dtrpg_url,
        itch_url=product.itch_url,
        themes=product.themes,
        content_warnings=product.content_warnings,
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
    text_extracted: bool | None = Query(None, description="Filter by text extraction status"),
    ai_identified: bool | None = Query(None, description="Filter by AI identification status"),
    publication_year_min: int | None = Query(None, description="Minimum publication year"),
    publication_year_max: int | None = Query(None, description="Maximum publication year"),
    level_min: int | None = Query(None, description="Minimum level (filters products with overlapping level range)"),
    level_max: int | None = Query(None, description="Maximum level (filters products with overlapping level range)"),
    party_size_min: int | None = Query(None, description="Minimum party size"),
    party_size_max: int | None = Query(None, description="Maximum party size"),
    estimated_runtime: str | None = Query(None, description="Filter by estimated runtime (partial match)"),
) -> ProductListResponse:
    """List products with filtering and pagination."""
    # Collect all filter conditions
    conditions = [Product.is_duplicate == False, Product.is_missing == False, Product.is_superseded == False]

    if search:
        search_term = f"%{search}%"
        ilike_condition = (
            (Product.title.ilike(search_term))
            | (Product.file_name.ilike(search_term))
            | (Product.description.ilike(search_term))
        )
        try:
            if await check_fts_available(db):
                terms = search.strip().split()
                if terms:
                    fts_query = " OR ".join(f'"{term}"*' for term in terms)
                    fts_limit = min(1000, (pagination.page * pagination.per_page) + 200)
                    fts_result = await db.execute(
                        text("SELECT rowid FROM products_fts WHERE products_fts MATCH :query LIMIT :limit"),
                        {"query": fts_query, "limit": fts_limit}
                    )
                    fts_product_ids = [row[0] for row in fts_result.fetchall()]
                    if fts_product_ids:
                        conditions.append(Product.id.in_(fts_product_ids))
                    else:
                        # FTS returned nothing — fall back to ILIKE
                        conditions.append(ilike_condition)
            else:
                conditions.append(ilike_condition)
        except Exception:
            conditions.append(ilike_condition)

    def _multi_value_filter(column, value: str):
        """Filter that matches exact value or as part of a comma-separated list."""
        if value == "Unknown":
            return column.is_(None)
        # Match exact value OR as part of a comma-separated list
        return (column == value) | column.like(f"{value}, %") | column.like(f"%, {value}") | column.like(f"%, {value}, %")

    if game_system:
        conditions.append(_multi_value_filter(Product.game_system, game_system))

    if product_type:
        if product_type == "Unknown":
            conditions.append(Product.product_type.is_(None))
        else:
            conditions.append(Product.product_type == product_type)

    if genre:
        conditions.append(_multi_value_filter(Product.genre, genre))

    if publisher:
        if publisher == "Unknown":
            conditions.append(Product.publisher.is_(None))
        else:
            conditions.append(Product.publisher == publisher)

    if author:
        conditions.append(_multi_value_filter(Product.author, author))

    if has_cover is not None:
        conditions.append(Product.cover_extracted == has_cover)

    if text_extracted is not None:
        conditions.append(Product.text_extracted == text_extracted)

    if ai_identified is not None:
        conditions.append(Product.ai_identified == ai_identified)

    if publication_year_min is not None:
        conditions.append(Product.publication_year >= publication_year_min)
    if publication_year_max is not None:
        conditions.append(Product.publication_year <= publication_year_max)

    if level_min is not None:
        conditions.append(
            (Product.level_range_max >= level_min) | (Product.level_range_max.is_(None))
        )
    if level_max is not None:
        conditions.append(
            (Product.level_range_min <= level_max) | (Product.level_range_min.is_(None))
        )

    if party_size_min is not None:
        conditions.append(
            (Product.party_size_max >= party_size_min) | (Product.party_size_max.is_(None))
        )
    if party_size_max is not None:
        conditions.append(
            (Product.party_size_min <= party_size_max) | (Product.party_size_min.is_(None))
        )

    if estimated_runtime:
        conditions.append(Product.estimated_runtime.ilike(f"%{estimated_runtime}%"))

    # Count query - lightweight, no eager loading or sorting
    count_query = select(func.count(Product.id)).where(*conditions)

    # Tags and collections require a join — apply to both count and main query
    if tags:
        tag_ids = [int(t.strip()) for t in tags.split(",") if t.strip().isdigit()]
        if tag_ids:
            count_query = count_query.join(ProductTag).where(ProductTag.tag_id.in_(tag_ids))

    if collection:
        from grimoire.models import CollectionProduct
        count_query = count_query.join(CollectionProduct).where(
            CollectionProduct.collection_id == collection
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Main query - with eager loading, sorting, pagination
    query = (
        select(Product)
        .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
        .where(*conditions)
    )

    if tags:
        tag_ids = [int(t.strip()) for t in tags.split(",") if t.strip().isdigit()]
        if tag_ids:
            query = query.join(ProductTag).where(ProductTag.tag_id.in_(tag_ids))

    if collection:
        from grimoire.models import CollectionProduct
        query = query.join(CollectionProduct).where(
            CollectionProduct.collection_id == collection
        )

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
    
    # Check if filter-relevant fields are being updated
    filter_fields = {'game_system', 'publisher', 'author', 'genre', 'product_type'}
    invalidate_cache = bool(filter_fields & update_dict.keys())
    
    for field, value in update_dict.items():
        setattr(product, field, value)

    product.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(product)

    # Invalidate filter cache if relevant fields changed
    if invalidate_cache:
        from grimoire.services.cache_service import get_cache_service
        cache = await get_cache_service()
        await cache.invalidate_filter_options()

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
    
    # Invalidate filter cache since product was deleted
    from grimoire.services.cache_service import get_cache_service
    cache = await get_cache_service()
    await cache.invalidate_filter_options()

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


@router.get("/{product_id}/thumbnail")
async def get_product_thumbnail(
    db: DbSession, 
    product_id: int,
    format: str = Query("webp", regex="^(webp|jpeg)$", description="Image format: webp or jpeg"),
) -> FileResponse:
    """Get the thumbnail image for a product.
    
    Thumbnails are optimized versions of cover images (300x400px).
    If thumbnail doesn't exist, returns the full cover and queues
    thumbnail generation in background.
    """
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # For duplicates, get the original's thumbnail
    if product.is_duplicate and product.duplicate_of_id:
        orig_query = select(Product).where(Product.id == product.duplicate_of_id)
        orig_result = await db.execute(orig_query)
        original = orig_result.scalar_one_or_none()
        if original and original.cover_extracted:
            product = original

    if not product.cover_extracted or not product.cover_image_path:
        raise HTTPException(status_code=404, detail="Cover not available")

    # Check if thumbnail exists, generate if not
    from grimoire.services.thumbnail_service import generate_thumbnail_for_product, get_thumbnail_path
    
    thumbnail_path = get_thumbnail_path(product, prefer_webp=(format == "webp"))
    
    if not thumbnail_path:
        # Queue thumbnail generation in background via asyncio.to_thread
        # Return the full cover immediately as a fallback
        asyncio.get_event_loop().run_in_executor(
            None, generate_thumbnail_for_product, product
        )

        cover_path = Path(product.cover_image_path)
        try:
            validate_covers_path(cover_path)
        except PathTraversalError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not cover_path.exists():
            raise HTTPException(status_code=404, detail="Cover file not found")

        return FileResponse(
            cover_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=60"},  # Short cache — thumbnail will be ready soon
        )
    
    # Validate path is within allowed directory
    try:
        validate_covers_path(thumbnail_path)
    except PathTraversalError:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not thumbnail_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail file not found")

    # Determine media type based on file extension
    media_type = "image/webp" if thumbnail_path.suffix == ".webp" else "image/jpeg"

    return FileResponse(
        thumbnail_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=2592000"},  # 30 days
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


@router.post("/{product_id}/open-folder")
async def open_product_folder(db: DbSession, product_id: int) -> dict:
    """Open the product's containing folder in the OS file explorer."""
    from grimoire.models import WatchedFolder

    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    folder_path = Path(product.file_path).parent

    # Validate path is within the product's watched folder
    if product.watched_folder_id:
        folder_result = await db.execute(
            select(WatchedFolder).where(WatchedFolder.id == product.watched_folder_id)
        )
        watched_folder = folder_result.scalar_one_or_none()
        if watched_folder:
            try:
                validate_path_in_directory(folder_path, watched_folder.path)
            except PathTraversalError:
                raise HTTPException(status_code=403, detail="Access denied")

    if not folder_path.exists():
        raise HTTPException(status_code=404, detail="Folder not found on disk")

    # Open folder in OS file explorer
    if sys.platform == "win32":
        subprocess.Popen(["explorer", str(folder_path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder_path)])
    else:
        subprocess.Popen(["xdg-open", str(folder_path)])

    return {"status": "ok", "folder": str(folder_path)}


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


@router.get("/{product_id}/images")
async def list_product_images(db: DbSession, product_id: int):
    """List extracted images for a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.images_extracted:
        return {"images": [], "image_count": 0, "total_pages": 0}

    manifest_path = settings.data_dir / "images" / str(product.id) / "manifest.json"
    if not manifest_path.exists():
        return {"images": [], "image_count": 0, "total_pages": 0}

    import json
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Add URLs to each image
    for img in manifest.get("images", []):
        img["url"] = f"/api/v1/products/{product_id}/images/{img['filename']}"

    return manifest


@router.get("/{product_id}/images/{filename}")
async def get_product_image(product_id: int, filename: str):
    """Serve a specific extracted image."""
    import re

    # Validate filename (prevent path traversal)
    if not re.match(r"^\d{3}\.(webp|jpg|jpeg|png)$", filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    image_path = settings.data_dir / "images" / str(product_id) / filename
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    # Determine media type
    suffix = image_path.suffix.lower()
    media_types = {".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(
        path=str(image_path),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


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

    import asyncio
    from grimoire.services.processor import process_text_extraction_sync

    # Run CPU-bound extraction in a thread to avoid blocking the event loop
    success = await asyncio.to_thread(process_text_extraction_sync, product, use_marker)

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
