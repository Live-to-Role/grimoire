"""Extraction API endpoints for TOC, tables, and content parsing."""

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from grimoire.api.deps import DbSession
from grimoire.models import Product
from grimoire.processors.toc_extractor import extract_toc, get_chapter_boundaries
from grimoire.processors.table_extractor import (
    extract_tables_from_pdf,
    tables_to_json,
    tables_to_rollable,
)
from grimoire.processors.statblock_extractor import (
    extract_statblocks_from_pdf,
    statblocks_to_json,
    statblocks_to_vtt,
)
from grimoire.processors.image_extractor import (
    extract_images_from_pdf,
    extract_maps_only,
    images_to_json,
    get_image_stats,
)
from grimoire.processors.text_extractor import get_gpu_status


router = APIRouter()


@router.get("/toc/{product_id}")
async def get_product_toc(
    db: DbSession,
    product_id: int,
) -> dict:
    """Extract table of contents from a product's PDF."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.file_path:
        raise HTTPException(status_code=400, detail="Product has no file path")

    toc_result = extract_toc(product.file_path)

    return {
        "product_id": product_id,
        "toc": toc_result.to_dict(),
        "chapters": get_chapter_boundaries(toc_result),
    }


@router.get("/toc/{product_id}/flat")
async def get_product_toc_flat(
    db: DbSession,
    product_id: int,
) -> dict:
    """Get flattened table of contents for a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.file_path:
        raise HTTPException(status_code=400, detail="Product has no file path")

    toc_result = extract_toc(product.file_path)

    return {
        "product_id": product_id,
        "entries": toc_result.flatten(),
        "method": toc_result.method,
    }


@router.get("/tables/{product_id}")
async def get_product_tables(
    db: DbSession,
    product_id: int,
    start_page: int = Query(1, ge=1),
    end_page: int | None = Query(None),
) -> dict:
    """Extract random/rollable tables from a product's PDF."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.file_path:
        raise HTTPException(status_code=400, detail="Product has no file path")

    tables = extract_tables_from_pdf(product.file_path, start_page, end_page)

    return {
        "product_id": product_id,
        "tables": tables_to_json(tables),
        "table_count": len(tables),
    }


@router.get("/tables/{product_id}/rollable")
async def get_product_tables_rollable(
    db: DbSession,
    product_id: int,
    start_page: int = Query(1, ge=1),
    end_page: int | None = Query(None),
) -> dict:
    """Get tables in rollable format for VTT export."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.file_path:
        raise HTTPException(status_code=400, detail="Product has no file path")

    tables = extract_tables_from_pdf(product.file_path, start_page, end_page)

    return {
        "product_id": product_id,
        "tables": tables_to_rollable(tables),
        "table_count": len(tables),
    }


@router.get("/statblocks/{product_id}")
async def get_product_statblocks(
    db: DbSession,
    product_id: int,
    start_page: int = Query(1, ge=1),
    end_page: int | None = Query(None),
    system: str | None = Query(None, description="System hint: 5e, pf2e, osr"),
) -> dict:
    """Extract stat blocks from a product's PDF."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.file_path:
        raise HTTPException(status_code=400, detail="Product has no file path")

    statblocks = extract_statblocks_from_pdf(
        product.file_path, start_page, end_page, system
    )

    return {
        "product_id": product_id,
        "statblocks": statblocks_to_json(statblocks),
        "statblock_count": len(statblocks),
    }


@router.get("/statblocks/{product_id}/vtt")
async def get_product_statblocks_vtt(
    db: DbSession,
    product_id: int,
    start_page: int = Query(1, ge=1),
    end_page: int | None = Query(None),
    format: str = Query("foundry", description="VTT format: foundry"),
) -> dict:
    """Get stat blocks in VTT-compatible format."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.file_path:
        raise HTTPException(status_code=400, detail="Product has no file path")

    statblocks = extract_statblocks_from_pdf(product.file_path, start_page, end_page)

    return {
        "product_id": product_id,
        "format": format,
        "statblocks": statblocks_to_vtt(statblocks, format),
        "statblock_count": len(statblocks),
    }


@router.get("/images/{product_id}")
async def get_product_images(
    db: DbSession,
    product_id: int,
    start_page: int = Query(1, ge=1),
    end_page: int | None = Query(None),
    min_width: int = Query(100, ge=10),
    min_height: int = Query(100, ge=10),
    maps_only: bool = Query(False),
) -> dict:
    """Extract images from a product's PDF."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.file_path:
        raise HTTPException(status_code=400, detail="Product has no file path")

    if maps_only:
        images = extract_maps_only(product.file_path, start_page, end_page)
    else:
        images = extract_images_from_pdf(
            product.file_path, start_page, end_page, min_width, min_height
        )

    return {
        "product_id": product_id,
        "images": images_to_json(images),
        "stats": get_image_stats(images),
    }


@router.get("/images/{product_id}/{image_index}")
async def get_product_image_data(
    db: DbSession,
    product_id: int,
    image_index: int,
    start_page: int = Query(1, ge=1),
    end_page: int | None = Query(None),
) -> dict:
    """Get a specific image with its data (base64 encoded)."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.file_path:
        raise HTTPException(status_code=400, detail="Product has no file path")

    images = extract_images_from_pdf(
        product.file_path, start_page, end_page, include_data=True
    )

    if image_index < 0 or image_index >= len(images):
        raise HTTPException(status_code=404, detail="Image not found")

    image = images[image_index]

    return {
        "product_id": product_id,
        "image": image.to_dict(include_data=True),
    }


@router.get("/gpu-status")
async def get_extraction_gpu_status() -> dict:
    """Get GPU availability status for ML-based extraction."""
    return get_gpu_status()
