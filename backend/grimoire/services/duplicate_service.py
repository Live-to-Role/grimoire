"""Service for detecting and managing duplicate products."""

import logging
from datetime import datetime, UTC
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Product

logger = logging.getLogger(__name__)


async def find_duplicates_by_hash(
    db: AsyncSession,
    file_hash: str,
    exclude_product_id: int | None = None,
) -> list[Product]:
    """Find products with the same file hash (exact duplicates)."""
    query = select(Product).where(Product.file_hash == file_hash)
    if exclude_product_id:
        query = query.where(Product.id != exclude_product_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def check_and_mark_duplicate(
    db: AsyncSession,
    product: Product,
) -> bool:
    """
    Check if a product is a duplicate and mark it accordingly.
    Returns True if product is a duplicate.
    """
    # Find existing products with same hash
    existing = await find_duplicates_by_hash(db, product.file_hash, product.id)
    
    if not existing:
        return False
    
    # Find the canonical (oldest) product
    canonical = min(existing, key=lambda p: p.created_at)
    
    # Mark this product as duplicate
    product.is_duplicate = True
    product.duplicate_of_id = canonical.id
    product.duplicate_reason = "exact_hash"
    
    await db.commit()
    logger.info(f"Marked product {product.id} as duplicate of {canonical.id}")
    return True


async def get_duplicate_groups(db: AsyncSession) -> list[dict[str, Any]]:
    """
    Get all groups of duplicate files.
    Returns list of groups, each with canonical product and duplicates.
    """
    # Find hashes that appear more than once
    hash_counts = (
        select(Product.file_hash, func.count(Product.id).label("count"))
        .where(Product.is_missing == False)
        .group_by(Product.file_hash)
        .having(func.count(Product.id) > 1)
    )
    
    result = await db.execute(hash_counts)
    duplicate_hashes = [row.file_hash for row in result.all()]
    
    groups = []
    for file_hash in duplicate_hashes:
        query = (
            select(Product)
            .where(Product.file_hash == file_hash)
            .order_by(Product.created_at)
        )
        result = await db.execute(query)
        products = list(result.scalars().all())
        
        if len(products) < 2:
            continue
        
        canonical = products[0]
        duplicates = products[1:]
        
        total_size = sum(p.file_size for p in duplicates)
        
        groups.append({
            "file_hash": file_hash,
            "canonical": {
                "id": canonical.id,
                "title": canonical.title or canonical.file_name,
                "file_path": canonical.file_path,
                "file_size": canonical.file_size,
            },
            "duplicates": [
                {
                    "id": p.id,
                    "title": p.title or p.file_name,
                    "file_path": p.file_path,
                    "file_size": p.file_size,
                }
                for p in duplicates
            ],
            "duplicate_count": len(duplicates),
            "wasted_space_bytes": total_size,
        })
    
    # Sort by wasted space descending
    groups.sort(key=lambda g: g["wasted_space_bytes"], reverse=True)
    return groups


async def get_duplicate_stats(db: AsyncSession) -> dict[str, Any]:
    """Get summary statistics about duplicates in the library."""
    # Total products
    total_query = select(func.count(Product.id)).where(Product.is_missing == False)
    total_result = await db.execute(total_query)
    total_products = total_result.scalar() or 0
    
    # Duplicate products
    dup_query = select(func.count(Product.id)).where(
        Product.is_duplicate == True,
        Product.is_missing == False,
    )
    dup_result = await db.execute(dup_query)
    duplicate_count = dup_result.scalar() or 0
    
    # Wasted space
    space_query = select(func.sum(Product.file_size)).where(
        Product.is_duplicate == True,
        Product.is_missing == False,
    )
    space_result = await db.execute(space_query)
    wasted_bytes = space_result.scalar() or 0
    
    # Unique hashes with duplicates
    groups = await get_duplicate_groups(db)
    
    return {
        "total_products": total_products,
        "duplicate_count": duplicate_count,
        "unique_duplicate_groups": len(groups),
        "wasted_space_bytes": wasted_bytes,
        "wasted_space_mb": round(wasted_bytes / (1024 * 1024), 2),
    }


async def scan_for_duplicates(db: AsyncSession) -> dict[str, int]:
    """
    Scan entire library for duplicates and mark them.
    Returns count of newly marked duplicates.
    """
    # Get all products grouped by hash
    query = select(Product).where(Product.is_missing == False).order_by(Product.file_hash, Product.created_at)
    result = await db.execute(query)
    products = list(result.scalars().all())
    
    # Group by hash
    hash_groups: dict[str, list[Product]] = {}
    for product in products:
        if product.file_hash not in hash_groups:
            hash_groups[product.file_hash] = []
        hash_groups[product.file_hash].append(product)
    
    marked = 0
    for file_hash, group in hash_groups.items():
        if len(group) < 2:
            continue
        
        # First product is canonical (oldest)
        canonical = group[0]
        canonical.is_duplicate = False
        canonical.duplicate_of_id = None
        canonical.duplicate_reason = None
        
        # Rest are duplicates
        for dup in group[1:]:
            if not dup.is_duplicate:
                dup.is_duplicate = True
                dup.duplicate_of_id = canonical.id
                dup.duplicate_reason = "exact_hash"
                marked += 1
    
    await db.commit()
    logger.info(f"Duplicate scan complete: marked {marked} duplicates")
    
    return {"marked": marked, "groups": len([g for g in hash_groups.values() if len(g) > 1])}


async def resolve_duplicate(
    db: AsyncSession,
    product_id: int,
    action: str,  # 'keep', 'remove_record', 'mark_canonical'
) -> dict[str, Any]:
    """
    Resolve a duplicate product.
    
    Actions:
    - keep: Keep as duplicate (no change)
    - remove_record: Remove from database (file stays)
    - mark_canonical: Make this the canonical version
    """
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()
    
    if not product:
        return {"success": False, "error": "Product not found"}
    
    if action == "keep":
        return {"success": True, "action": "kept as duplicate"}
    
    elif action == "remove_record":
        await db.delete(product)
        await db.commit()
        return {"success": True, "action": "record removed"}
    
    elif action == "mark_canonical":
        if not product.duplicate_of_id:
            return {"success": False, "error": "Product is not a duplicate"}
        
        old_canonical_id = product.duplicate_of_id
        
        # Get all products in this duplicate group
        old_canonical_query = select(Product).where(Product.id == old_canonical_id)
        old_result = await db.execute(old_canonical_query)
        old_canonical = old_result.scalar_one_or_none()
        
        if old_canonical:
            # Swap: old canonical becomes duplicate
            old_canonical.is_duplicate = True
            old_canonical.duplicate_of_id = product.id
            old_canonical.duplicate_reason = "exact_hash"
        
        # This product becomes canonical
        product.is_duplicate = False
        product.duplicate_of_id = None
        product.duplicate_reason = None
        
        # Update any other duplicates to point to new canonical
        update_query = select(Product).where(Product.duplicate_of_id == old_canonical_id)
        update_result = await db.execute(update_query)
        for dup in update_result.scalars().all():
            if dup.id != product.id:
                dup.duplicate_of_id = product.id
        
        await db.commit()
        return {"success": True, "action": "marked as canonical"}
    
    return {"success": False, "error": f"Unknown action: {action}"}


async def bulk_delete_duplicates(
    db: AsyncSession,
    product_ids: list[int],
    delete_files: bool = False,
) -> dict[str, Any]:
    """
    Delete multiple duplicate products.
    
    Args:
        db: Database session
        product_ids: List of product IDs to delete
        delete_files: If True, also delete the actual files from disk
        
    Returns:
        Summary of deletions
    """
    from pathlib import Path
    
    deleted_records = 0
    deleted_files = 0
    errors = []
    space_freed = 0
    
    for product_id in product_ids:
        query = select(Product).where(Product.id == product_id)
        result = await db.execute(query)
        product = result.scalar_one_or_none()
        
        if not product:
            errors.append(f"Product {product_id} not found")
            continue
        
        # Only allow deleting duplicates, not canonical products
        if not product.is_duplicate:
            errors.append(f"Product {product_id} is not a duplicate")
            continue
        
        space_freed += product.file_size or 0
        
        # Delete the actual file if requested
        if delete_files:
            try:
                file_path = Path(product.file_path)
                if file_path.exists():
                    file_path.unlink()
                    deleted_files += 1
                    logger.info(f"Deleted file: {product.file_path}")
            except Exception as e:
                errors.append(f"Failed to delete file for {product_id}: {str(e)}")
        
        # Delete the database record
        await db.delete(product)
        deleted_records += 1
    
    await db.commit()
    
    # Clean up any orphaned duplicates that may have resulted
    cleanup_result = await cleanup_orphaned_duplicates(db)
    
    return {
        "success": True,
        "deleted_records": deleted_records,
        "deleted_files": deleted_files,
        "space_freed_bytes": space_freed,
        "space_freed_mb": round(space_freed / (1024 * 1024), 2),
        "orphans_cleaned": cleanup_result.get("cleaned", 0),
        "errors": errors,
    }


async def delete_all_duplicates_in_group(
    db: AsyncSession,
    file_hash: str,
    delete_files: bool = False,
) -> dict[str, Any]:
    """
    Delete all duplicates in a group, keeping only the canonical.
    
    Args:
        db: Database session
        file_hash: The file hash identifying the duplicate group
        delete_files: If True, also delete the actual files from disk
        
    Returns:
        Summary of deletions
    """
    # Get all products with this hash
    query = select(Product).where(Product.file_hash == file_hash).order_by(Product.created_at)
    result = await db.execute(query)
    products = list(result.scalars().all())
    
    if len(products) < 2:
        return {"success": False, "error": "No duplicate group found for this hash"}
    
    # First product is canonical, rest are duplicates
    canonical = products[0]
    duplicates = products[1:]
    
    # Get IDs of duplicates to delete
    duplicate_ids = [p.id for p in duplicates]
    
    # Use bulk delete function
    return await bulk_delete_duplicates(db, duplicate_ids, delete_files=delete_files)


async def cleanup_orphaned_duplicates(db: AsyncSession) -> dict[str, Any]:
    """
    Clean up orphaned duplicates - products marked as duplicates but whose
    canonical product was deleted.
    
    Returns:
        Summary of cleanup
    """
    # Find orphaned duplicates
    query = select(Product).where(
        Product.is_duplicate == True,
        Product.duplicate_of_id.isnot(None),
    )
    result = await db.execute(query)
    duplicates = list(result.scalars().all())
    
    cleaned = 0
    for dup in duplicates:
        # Check if canonical exists
        canonical_query = select(Product).where(Product.id == dup.duplicate_of_id)
        canonical_result = await db.execute(canonical_query)
        canonical = canonical_result.scalar_one_or_none()
        
        if not canonical:
            # Canonical was deleted, unmark as duplicate
            dup.is_duplicate = False
            dup.duplicate_of_id = None
            dup.duplicate_reason = None
            cleaned += 1
    
    if cleaned > 0:
        await db.commit()
        logger.info(f"Cleaned up {cleaned} orphaned duplicate records")
    
    return {"cleaned": cleaned}
