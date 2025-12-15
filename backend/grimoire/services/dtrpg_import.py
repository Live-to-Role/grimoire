"""DriveThruRPG library import service.

Imports product metadata from DriveThruRPG library export JSON and matches
to local files by filename.

Supports two formats:
1. Library search endpoint (your current JSON): /api/products/mylibrary/search
2. V1 API endpoint (richer data): /api/v1/customers/<id>/products

See: https://github.com/jramboz/DTRPG_API for API documentation.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Product

logger = logging.getLogger(__name__)


@dataclass
class DTRPGProduct:
    """Parsed DriveThruRPG product data."""
    product_id: str
    title: str
    publisher: str
    publisher_url: str | None
    product_url: str
    filenames: list[str]
    updated: str | None
    cover_url: str | None = None
    filters: list[str] = field(default_factory=list)  # Categories/tags from DTRPG
    
    @classmethod
    def from_library_search(cls, data: dict[str, Any]) -> "DTRPGProduct":
        """Parse from library search endpoint (/api/products/mylibrary/search)."""
        product = data.get("product", {})
        publisher = data.get("publisher", {})
        
        # Extract filenames from files array
        filenames = []
        for file_entry in product.get("files", []):
            if file_entry.get("title"):
                filenames.append(file_entry["title"])
        
        return cls(
            product_id=str(data.get("p_id", "")),
            title=product.get("title", "").strip(),
            publisher=publisher.get("title", "").strip(),
            publisher_url=publisher.get("url"),
            product_url=product.get("url", ""),
            filenames=filenames,
            updated=data.get("updated"),
        )
    
    @classmethod
    def from_v1_api(cls, data: dict[str, Any]) -> "DTRPGProduct":
        """Parse from V1 API endpoint (/api/v1/customers/<id>/products)."""
        # Extract filenames from embedded files
        filenames = []
        if "files" in data:
            for file_entry in data["files"]:
                if file_entry.get("filename"):
                    filenames.append(file_entry["filename"])
        
        # Extract filter names (categories/tags)
        filters = []
        if "filters" in data:
            for f in data["filters"]:
                if f.get("filters_name"):
                    filters.append(f["filters_name"])
        
        return cls(
            product_id=str(data.get("products_id", "")),
            title=data.get("products_name", "").strip(),
            publisher=data.get("publishers_name", "").strip(),
            publisher_url=None,
            product_url="",
            filenames=filenames,
            updated=data.get("date_purchased"),
            cover_url=data.get("cover_url_fullsize") or data.get("cover_url"),
            filters=filters,
        )
    
    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "DTRPGProduct":
        """Auto-detect format and parse."""
        # V1 API uses products_id, library search uses p_id
        if "products_id" in data:
            return cls.from_v1_api(data)
        else:
            return cls.from_library_search(data)


def parse_dtrpg_library(json_data: dict[str, Any]) -> list[DTRPGProduct]:
    """Parse DriveThruRPG library JSON export.
    
    Args:
        json_data: Parsed JSON from DTRPG API
        
    Returns:
        List of DTRPGProduct objects
    """
    if json_data.get("status") != "success":
        raise ValueError(f"DTRPG API returned error status: {json_data.get('status')}")
    
    products = []
    for item in json_data.get("data", []):
        try:
            product = DTRPGProduct.from_json(item)
            if product.product_id and product.title:
                products.append(product)
        except Exception as e:
            logger.warning(f"Failed to parse DTRPG product: {e}")
    
    return products


def normalize_filename(filename: str) -> str:
    """Normalize a filename for matching.
    
    Removes common variations like spaces, underscores, case differences.
    """
    # Remove extension
    name = Path(filename).stem.lower()
    # Replace common separators with space
    name = re.sub(r"[-_.]", " ", name)
    # Remove extra whitespace
    name = re.sub(r"\s+", " ", name).strip()
    # Remove common suffixes
    name = re.sub(r"\s*(print|screen|printer|web|lite|free|preview|sample)$", "", name, flags=re.IGNORECASE)
    return name


def build_filename_index(products: list[DTRPGProduct]) -> dict[str, DTRPGProduct]:
    """Build an index of normalized filenames to DTRPG products.
    
    Args:
        products: List of DTRPG products
        
    Returns:
        Dict mapping normalized filename to product
    """
    index = {}
    for product in products:
        for filename in product.filenames:
            normalized = normalize_filename(filename)
            if normalized:
                # If duplicate, prefer the one with more files (likely the main product)
                if normalized not in index or len(product.filenames) > len(index[normalized].filenames):
                    index[normalized] = product
    return index


async def match_products_to_dtrpg(
    db: AsyncSession,
    dtrpg_products: list[DTRPGProduct],
    batch_size: int = 500,
) -> dict[str, Any]:
    """Match local products to DTRPG library entries by filename.
    
    Optimized for large libraries - processes in batches and uses
    database queries instead of loading everything into memory.
    
    Args:
        db: Database session
        dtrpg_products: Parsed DTRPG products
        batch_size: Number of products to process per batch
        
    Returns:
        Dict with match statistics and results
    """
    # Build filename index (normalized filename -> DTRPG product)
    filename_index = build_filename_index(dtrpg_products)
    logger.info(f"Built DTRPG filename index with {len(filename_index)} entries")
    
    # Get total count first
    count_query = select(func.count(Product.id)).where(
        Product.is_duplicate == False,
        Product.is_missing == False,
    )
    count_result = await db.execute(count_query)
    total_local = count_result.scalar() or 0
    
    matched = 0
    updated = 0
    unmatched_sample = []
    offset = 0
    
    # Process in batches to avoid memory issues
    while True:
        query = select(Product).where(
            Product.is_duplicate == False,
            Product.is_missing == False,
        ).offset(offset).limit(batch_size)
        
        result = await db.execute(query)
        batch = list(result.scalars().all())
        
        if not batch:
            break
        
        for product in batch:
            normalized_name = normalize_filename(product.file_name)
            dtrpg_match = filename_index.get(normalized_name)
            
            if dtrpg_match:
                matched += 1
                changes = False
                
                # Update publisher if not set
                if not product.publisher and dtrpg_match.publisher:
                    product.publisher = dtrpg_match.publisher
                    changes = True
                
                # Update title if it's just the filename
                if product.title == Path(product.file_name).stem and dtrpg_match.title:
                    product.title = dtrpg_match.title
                    changes = True
                
                if changes:
                    updated += 1
            else:
                # Only keep first 20 unmatched for sample
                if len(unmatched_sample) < 20:
                    unmatched_sample.append({
                        "id": product.id,
                        "filename": product.file_name,
                        "normalized": normalized_name,
                    })
        
        # Commit each batch with retry for database locks
        for retry in range(3):
            try:
                await db.commit()
                break
            except Exception as e:
                if "database is locked" in str(e) and retry < 2:
                    import asyncio
                    await asyncio.sleep(1)
                    continue
                raise
        
        offset += batch_size
        logger.info(f"Processed {min(offset, total_local)}/{total_local} products, {matched} matched")
    
    return {
        "total_local": total_local,
        "total_dtrpg": len(dtrpg_products),
        "matched": matched,
        "updated": updated,
        "unmatched_count": total_local - matched,
        "unmatched_sample": unmatched_sample,
        "match_rate": f"{(matched / total_local * 100):.1f}%" if total_local else "0%",
    }


async def import_dtrpg_library(
    db: AsyncSession,
    json_path: str | Path | None = None,
    json_data: dict[str, Any] | None = None,
    apply: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    """Import DriveThruRPG library and match to local products.
    
    Args:
        db: Database session
        json_path: Path to DTRPG JSON file
        json_data: Already parsed JSON data (alternative to json_path)
        apply: If True, update products with matched metadata
        limit: Maximum number of products to process
        
    Returns:
        Import statistics
    """
    # Load JSON
    if json_data is None:
        if json_path is None:
            raise ValueError("Either json_path or json_data must be provided")
        
        json_path = Path(json_path)
        if not json_path.exists():
            raise FileNotFoundError(f"DTRPG JSON file not found: {json_path}")
        
        with open(json_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)
    
    # Parse products
    dtrpg_products = parse_dtrpg_library(json_data)
    logger.info(f"Parsed {len(dtrpg_products)} products from DTRPG library")
    
    if not apply:
        # Dry run - just return stats
        filename_index = build_filename_index(dtrpg_products)
        return {
            "dry_run": True,
            "total_dtrpg_products": len(dtrpg_products),
            "unique_filenames": len(filename_index),
            "sample_products": [
                {"title": p.title, "publisher": p.publisher, "files": p.filenames[:3]}
                for p in dtrpg_products[:10]
            ],
        }
    
    # Match and update
    return await match_products_to_dtrpg(db, dtrpg_products)


def get_dtrpg_stats(json_data: dict[str, Any]) -> dict[str, Any]:
    """Get statistics about a DTRPG library export.
    
    Args:
        json_data: Parsed DTRPG JSON
        
    Returns:
        Statistics dict
    """
    products = parse_dtrpg_library(json_data)
    
    # Count publishers
    publishers = {}
    for p in products:
        pub = p.publisher or "Unknown"
        publishers[pub] = publishers.get(pub, 0) + 1
    
    # Sort by count
    top_publishers = sorted(publishers.items(), key=lambda x: x[1], reverse=True)[:20]
    
    # Count total files
    total_files = sum(len(p.filenames) for p in products)
    
    return {
        "total_products": len(products),
        "total_files": total_files,
        "unique_publishers": len(publishers),
        "top_publishers": [{"name": name, "count": count} for name, count in top_publishers],
    }
