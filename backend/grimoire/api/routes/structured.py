"""Structured content extraction API endpoints."""

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from grimoire.api.deps import DbSession
from grimoire.models import Product
from grimoire.services.processor import get_extracted_text
from grimoire.processors.structured_extractor import (
    extract_monsters,
    extract_spells,
    extract_magic_items,
    extract_npcs,
)
from grimoire.schemas.ttrpg import Monster, Spell, MagicItem, NPC, ExtractedContent


router = APIRouter()


class ExtractionRequest(BaseModel):
    """Request for structured extraction."""
    provider: str | None = Field(None, description="AI provider: openai, anthropic")
    model: str | None = Field(None, description="Specific model to use")
    page_start: int | None = Field(None, ge=1)
    page_end: int | None = Field(None, ge=1)


@router.post("/monsters/{product_id}")
async def extract_product_monsters(
    db: DbSession,
    product_id: int,
    request: ExtractionRequest,
) -> dict:
    """Extract monster stat blocks from a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    text = get_extracted_text(product)
    if not text:
        raise HTTPException(status_code=400, detail="Product has no extracted text")

    try:
        monsters = await extract_monsters(text, request.provider, request.model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    return {
        "product_id": product_id,
        "monsters": monsters,
        "count": len(monsters),
    }


@router.post("/spells/{product_id}")
async def extract_product_spells(
    db: DbSession,
    product_id: int,
    request: ExtractionRequest,
) -> dict:
    """Extract spell definitions from a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    text = get_extracted_text(product)
    if not text:
        raise HTTPException(status_code=400, detail="Product has no extracted text")

    try:
        spells = await extract_spells(text, request.provider, request.model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    return {
        "product_id": product_id,
        "spells": spells,
        "count": len(spells),
    }


@router.post("/magic-items/{product_id}")
async def extract_product_magic_items(
    db: DbSession,
    product_id: int,
    request: ExtractionRequest,
) -> dict:
    """Extract magic item definitions from a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    text = get_extracted_text(product)
    if not text:
        raise HTTPException(status_code=400, detail="Product has no extracted text")

    try:
        items = await extract_magic_items(text, request.provider, request.model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    return {
        "product_id": product_id,
        "magic_items": items,
        "count": len(items),
    }


@router.post("/npcs/{product_id}")
async def extract_product_npcs(
    db: DbSession,
    product_id: int,
    request: ExtractionRequest,
) -> dict:
    """Extract NPC definitions from a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    text = get_extracted_text(product)
    if not text:
        raise HTTPException(status_code=400, detail="Product has no extracted text")

    try:
        npcs = await extract_npcs(text, request.provider, request.model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    return {
        "product_id": product_id,
        "npcs": npcs,
        "count": len(npcs),
    }


@router.post("/all/{product_id}")
async def extract_all_structured_content(
    db: DbSession,
    product_id: int,
    request: ExtractionRequest,
    monsters: bool = Query(True),
    spells: bool = Query(True),
    items: bool = Query(True),
    npcs: bool = Query(True),
) -> dict:
    """Extract all structured content from a product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    text = get_extracted_text(product)
    if not text:
        raise HTTPException(status_code=400, detail="Product has no extracted text")

    extracted = {
        "product_id": product_id,
        "product_title": product.title,
    }

    try:
        if monsters:
            extracted["monsters"] = await extract_monsters(text, request.provider, request.model)
        if spells:
            extracted["spells"] = await extract_spells(text, request.provider, request.model)
        if items:
            extracted["magic_items"] = await extract_magic_items(text, request.provider, request.model)
        if npcs:
            extracted["npcs"] = await extract_npcs(text, request.provider, request.model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    return extracted
