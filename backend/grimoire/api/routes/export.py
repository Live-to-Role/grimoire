"""Export API endpoints for Foundry VTT and Obsidian."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
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
from grimoire.exporters.foundry import (
    monster_to_foundry,
    spell_to_foundry,
    magic_item_to_foundry,
    export_to_foundry_compendium,
)
from grimoire.exporters.obsidian import (
    monster_to_obsidian,
    spell_to_obsidian,
    magic_item_to_obsidian,
    npc_to_obsidian,
    export_to_obsidian_vault,
)


router = APIRouter()


class ExportRequest(BaseModel):
    """Request for export."""
    provider: str | None = Field(None, description="AI provider for extraction")
    model: str | None = Field(None, description="Specific model to use")
    monsters: bool = Field(True)
    spells: bool = Field(True)
    items: bool = Field(True)
    npcs: bool = Field(True)


@router.post("/foundry/{product_id}")
async def export_to_foundry(
    db: DbSession,
    product_id: int,
    request: ExportRequest,
) -> dict:
    """Export extracted content to Foundry VTT format."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    text = get_extracted_text(product)
    if not text:
        raise HTTPException(status_code=400, detail="Product has no extracted text")

    extracted = {}

    try:
        if request.monsters:
            monsters = await extract_monsters(text, request.provider, request.model)
            extracted["monsters"] = monsters
        if request.spells:
            spells = await extract_spells(text, request.provider, request.model)
            extracted["spells"] = spells
        if request.items:
            items = await extract_magic_items(text, request.provider, request.model)
            extracted["items"] = items
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    # Convert to Foundry format
    foundry_export = export_to_foundry_compendium(
        monsters=extracted.get("monsters"),
        spells=extracted.get("spells"),
        items=extracted.get("items"),
    )

    foundry_export["source_product"] = {
        "id": product_id,
        "title": product.title,
        "file_name": product.file_name,
    }

    return foundry_export


@router.post("/obsidian/{product_id}")
async def export_to_obsidian(
    db: DbSession,
    product_id: int,
    request: ExportRequest,
) -> dict:
    """Export extracted content to Obsidian markdown format."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    text = get_extracted_text(product)
    if not text:
        raise HTTPException(status_code=400, detail="Product has no extracted text")

    extracted = {}

    try:
        if request.monsters:
            extracted["monsters"] = await extract_monsters(text, request.provider, request.model)
        if request.spells:
            extracted["spells"] = await extract_spells(text, request.provider, request.model)
        if request.items:
            extracted["items"] = await extract_magic_items(text, request.provider, request.model)
        if request.npcs:
            extracted["npcs"] = await extract_npcs(text, request.provider, request.model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    # Convert to Obsidian format
    files = export_to_obsidian_vault(
        monsters=extracted.get("monsters"),
        spells=extracted.get("spells"),
        items=extracted.get("items"),
        npcs=extracted.get("npcs"),
    )

    return {
        "source_product": {
            "id": product_id,
            "title": product.title,
        },
        "file_count": len(files),
        "files": files,
    }


@router.get("/obsidian/{product_id}/file/{content_type}/{name}")
async def get_obsidian_file(
    db: DbSession,
    product_id: int,
    content_type: str,
    name: str,
    provider: str | None = Query(None),
) -> PlainTextResponse:
    """Get a single Obsidian markdown file."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    text = get_extracted_text(product)
    if not text:
        raise HTTPException(status_code=400, detail="Product has no extracted text")

    # Extract based on content type
    try:
        if content_type == "monsters":
            items = await extract_monsters(text, provider)
            converter = monster_to_obsidian
        elif content_type == "spells":
            items = await extract_spells(text, provider)
            converter = spell_to_obsidian
        elif content_type == "items":
            items = await extract_magic_items(text, provider)
            converter = magic_item_to_obsidian
        elif content_type == "npcs":
            items = await extract_npcs(text, provider)
            converter = npc_to_obsidian
        else:
            raise HTTPException(status_code=400, detail=f"Unknown content type: {content_type}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    # Find the item by name
    for item in items:
        item_name = item.get("name", "") if isinstance(item, dict) else item.name
        if item_name.lower().replace(" ", "_") == name.lower().replace(" ", "_"):
            return PlainTextResponse(
                content=converter(item),
                media_type="text/markdown",
            )

    raise HTTPException(status_code=404, detail=f"{content_type[:-1].title()} not found: {name}")


@router.get("/formats")
async def list_export_formats() -> dict:
    """List available export formats."""
    return {
        "formats": [
            {
                "id": "foundry",
                "name": "Foundry VTT",
                "description": "Export to Foundry VTT compendium JSON format (dnd5e system)",
                "content_types": ["monsters", "spells", "items", "tables"],
            },
            {
                "id": "obsidian",
                "name": "Obsidian Markdown",
                "description": "Export to Obsidian-compatible markdown with YAML frontmatter",
                "content_types": ["monsters", "spells", "items", "npcs", "locations", "tables"],
            },
        ]
    }
