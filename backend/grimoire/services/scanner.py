"""Library scanner service - scans folders for PDF files."""

import hashlib
import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Product, WatchedFolder
from grimoire.services.exclusion_service import create_exclusion_matcher, increment_rule_match
from grimoire.services.duplicate_service import batch_check_and_mark_duplicates, check_and_mark_duplicate, is_deleted_duplicate

logger = logging.getLogger(__name__)


async def calculate_file_hash(file_path: Path, max_bytes: int = 1024 * 1024) -> str:
    """Calculate SHA-256 hash of file header for fast identification.
    
    Uses first max_bytes (default 1MB) + file size for quick fingerprinting.
    This is much faster than hashing entire files while still catching most changes.
    """
    sha256_hash = hashlib.sha256()
    file_size = file_path.stat().st_size
    
    # Include file size in hash for additional uniqueness
    sha256_hash.update(str(file_size).encode())
    
    with open(file_path, "rb") as f:
        # Read only first max_bytes for speed
        data = f.read(max_bytes)
        sha256_hash.update(data)
    
    return sha256_hash.hexdigest()


def is_pdf_file(filename: str) -> bool:
    """Check if a file is a PDF based on extension."""
    return filename.lower().endswith(".pdf")


async def scan_folder(
    db: AsyncSession,
    folder: WatchedFolder,
    force: bool = False,
) -> dict[str, Any]:
    """Scan a folder for PDF files and add them to the database.

    Args:
        db: Database session
        folder: The watched folder to scan
        force: If True, re-scan files even if they haven't changed

    Returns:
        Dict with scan results including products, excluded, duplicates
    """
    folder_path = Path(folder.path)
    if not folder_path.exists():
        return {"products": [], "excluded": 0, "duplicates": 0, "errors": 0}

    # Get exclusion matcher
    exclusion_matcher = await create_exclusion_matcher(db)
    
    products = []
    excluded_count = 0
    duplicate_count = 0
    error_count = 0

    for pdf_path in folder_path.rglob("*.pdf"):
        if not pdf_path.is_file():
            continue

        try:
            stat = pdf_path.stat()
            file_size = stat.st_size
        except OSError as e:
            logger.warning(f"Cannot stat file {pdf_path}: {e}")
            error_count += 1
            continue

        # Check exclusion rules
        should_exclude, matching_rule = exclusion_matcher.should_exclude(pdf_path, file_size)
        if should_exclude:
            logger.debug(f"Excluding {pdf_path}: {matching_rule.description if matching_rule else 'unknown'}")
            if matching_rule:
                await increment_rule_match(db, matching_rule.id)
            excluded_count += 1
            continue

        file_path_str = str(pdf_path)

        # Skip files that were previously deleted as duplicates
        if await is_deleted_duplicate(db, file_path_str):
            logger.debug(f"Skipping deleted duplicate: {file_path_str}")
            continue

        existing_query = select(Product).where(Product.file_path == file_path_str)
        existing_result = await db.execute(existing_query)
        existing_product = existing_result.scalar_one_or_none()

        file_modified = datetime.fromtimestamp(stat.st_mtime)

        if existing_product and not force:
            # Clear missing flag if file reappeared
            if existing_product.is_missing:
                existing_product.is_missing = False
                existing_product.missing_since = None
            
            # Skip if file unchanged (size + mtime match)
            if (
                existing_product.file_size == file_size
                and existing_product.file_modified_at
                and existing_product.file_modified_at >= file_modified
            ):
                continue

        # Only hash when file is new or changed (much faster than before)
        file_hash = await calculate_file_hash(pdf_path)

        if existing_product:
            if existing_product.file_hash == file_hash and not force:
                continue

            existing_product.file_size = file_size
            existing_product.file_hash = file_hash
            existing_product.file_modified_at = file_modified
            existing_product.updated_at = datetime.now(UTC)
            
            # Check for duplicates after hash update
            if await check_and_mark_duplicate(db, existing_product):
                duplicate_count += 1
            
            products.append(existing_product)
        else:
            product = Product(
                file_path=file_path_str,
                file_name=pdf_path.name,
                file_size=file_size,
                file_hash=file_hash,
                watched_folder_id=folder.id,
                file_modified_at=file_modified,
                title=pdf_path.stem,
            )
            db.add(product)
            products.append(product)
            
        # Commit in batches of 100 for better performance
        if len(products) % 100 == 0:
            await db.flush()
            batch = products[-100:]
            duplicate_count += await batch_check_and_mark_duplicates(db, batch)
            await db.commit()
            await queue_products_for_processing(db, batch)

    # Final flush and duplicate check for remaining products
    await db.flush()
    remaining = products[-(len(products) % 100):] if len(products) % 100 != 0 else []
    if remaining:
        duplicate_count += await batch_check_and_mark_duplicates(db, remaining)
    await db.commit()

    if remaining:
        await queue_products_for_processing(db, remaining)

    return {
        "products": products,
        "new_count": len(products),
        "excluded": excluded_count,
        "duplicates": duplicate_count,
        "errors": error_count,
    }


async def get_scan_settings(db: AsyncSession) -> dict:
    """Get scan-related settings from the database."""
    from grimoire.models import Setting
    import json
    
    settings = {}
    query = select(Setting).where(Setting.key.in_([
        'auto_extract_text_on_scan',
        'auto_identify_on_scan',
    ]))
    result = await db.execute(query)
    for setting in result.scalars().all():
        try:
            settings[setting.key] = json.loads(setting.value)
        except (json.JSONDecodeError, TypeError):
            settings[setting.key] = setting.value
    
    return settings


async def queue_products_for_processing(db: AsyncSession, products: list[Product]) -> dict:
    """Queue products for processing based on settings.

    Uses batch queries to check for existing queue items instead of
    per-product queries. This reduces N*M queries to 1 query.
    """
    from grimoire.models import ProcessingQueue

    settings = await get_scan_settings(db)
    auto_extract_text = settings.get('auto_extract_text_on_scan', False)
    auto_identify = settings.get('auto_identify_on_scan', False)

    # Filter out duplicates
    eligible = [p for p in products if not p.is_duplicate]
    if not eligible:
        return {"covers": 0, "text": 0}

    product_ids = [p.id for p in eligible]

    # Batch-fetch all existing pending/processing queue items for these products
    existing_result = await db.execute(
        select(ProcessingQueue.product_id, ProcessingQueue.task_type)
        .where(
            ProcessingQueue.product_id.in_(product_ids),
            ProcessingQueue.status.in_(["pending", "processing"]),
        )
    )
    existing_tasks = {(row[0], row[1]) for row in existing_result.fetchall()}

    queued_covers = 0
    queued_text = 0

    for product in eligible:
        if not product.cover_extracted and (product.id, "cover") not in existing_tasks:
            db.add(ProcessingQueue(
                product_id=product.id,
                task_type="cover",
                priority=3,
                status="pending",
            ))
            queued_covers += 1

        if auto_extract_text and not product.text_extracted:
            if (product.id, "text") not in existing_tasks:
                db.add(ProcessingQueue(
                    product_id=product.id,
                    task_type="text",
                    priority=5,
                    status="pending",
                ))
                queued_text += 1

        if auto_identify and product.text_extracted and not product.ai_identified:
            if (product.id, "ai_identify") not in existing_tasks:
                db.add(ProcessingQueue(
                    product_id=product.id,
                    task_type="ai_identify",
                    priority=7,
                    status="pending",
                ))

    if queued_covers > 0 or queued_text > 0:
        await db.commit()

    return {"covers": queued_covers, "text": queued_text}


async def mark_missing_products(db: AsyncSession, folder: WatchedFolder) -> int:
    """Mark products whose files no longer exist as missing (soft delete).

    Args:
        db: Database session
        folder: The watched folder to check

    Returns:
        Number of products marked as missing
    """
    query = select(Product).where(
        Product.watched_folder_id == folder.id,
        Product.is_missing == False,
    )
    result = await db.execute(query)
    products = result.scalars().all()

    marked = 0
    now = datetime.now(UTC)
    
    for product in products:
        if not Path(product.file_path).exists():
            product.is_missing = True
            product.missing_since = now
            marked += 1
            logger.info(f"Marked product {product.id} as missing: {product.file_path}")

    if marked > 0:
        await db.commit()
    
    return marked


async def remove_missing_products(db: AsyncSession, folder: WatchedFolder) -> int:
    """Hard delete products that have been missing for a while.
    
    Only removes products marked as missing. Use mark_missing_products first.

    Args:
        db: Database session
        folder: The watched folder to check

    Returns:
        Number of products removed
    """
    query = select(Product).where(
        Product.watched_folder_id == folder.id,
        Product.is_missing == True,
    )
    result = await db.execute(query)
    products = result.scalars().all()

    removed = 0
    for product in products:
        await db.delete(product)
        removed += 1
        logger.info(f"Removed missing product {product.id}: {product.file_path}")

    if removed > 0:
        await db.commit()
    
    return removed
