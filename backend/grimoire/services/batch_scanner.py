"""Batch scanning service with progress tracking for large libraries."""

import asyncio
import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Product, WatchedFolder, ScanJob, ScanJobStatus
from grimoire.services.scanner import calculate_file_hash
from grimoire.services.exclusion_service import create_exclusion_matcher, increment_rule_match
from grimoire.services.duplicate_service import check_and_mark_duplicate

logger = logging.getLogger(__name__)

# Default batch size for processing
DEFAULT_BATCH_SIZE = 100


async def create_scan_job(
    db: AsyncSession,
    folder_id: int | None = None,
) -> ScanJob:
    """Create a new scan job."""
    job = ScanJob(
        watched_folder_id=folder_id,
        status=ScanJobStatus.PENDING.value,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_active_scan_job(db: AsyncSession) -> ScanJob | None:
    """Get the currently running scan job, if any."""
    query = select(ScanJob).where(
        ScanJob.status.in_([
            ScanJobStatus.PENDING.value,
            ScanJobStatus.SCANNING.value,
            ScanJobStatus.HASHING.value,
            ScanJobStatus.PROCESSING.value,
        ])
    ).order_by(ScanJob.created_at.desc())
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_scan_job(db: AsyncSession, job_id: int) -> ScanJob | None:
    """Get a scan job by ID."""
    query = select(ScanJob).where(ScanJob.id == job_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def discover_files(
    folder_path: Path,
) -> list[tuple[Path, int]]:
    """
    Phase 1: Discover all PDF files in a folder.
    Returns list of (path, size) tuples.
    """
    files = []
    for pdf_path in folder_path.rglob("*.pdf"):
        if not pdf_path.is_file():
            continue
        try:
            size = pdf_path.stat().st_size
            files.append((pdf_path, size))
        except OSError:
            continue
    return files


async def batch_scan_folder(
    db: AsyncSession,
    folder: WatchedFolder,
    job: ScanJob,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """
    Scan a folder in batches with progress tracking.
    
    Args:
        db: Database session
        folder: Folder to scan
        job: ScanJob to update with progress
        batch_size: Number of files to process per batch
        
    Returns:
        Final scan results
    """
    folder_path = Path(folder.path)
    if not folder_path.exists():
        job.status = ScanJobStatus.FAILED.value
        job.error_message = f"Folder does not exist: {folder.path}"
        await db.commit()
        return {"error": job.error_message}
    
    # Phase 1: Discovery
    job.status = ScanJobStatus.SCANNING.value
    job.current_phase = "Discovering files"
    job.started_at = datetime.now(UTC)
    await db.commit()
    
    all_files = await discover_files(folder_path)
    job.total_files = len(all_files)
    await db.commit()
    
    logger.info(f"Discovered {len(all_files)} PDF files in {folder.path}")
    
    # Get exclusion matcher
    exclusion_matcher = await create_exclusion_matcher(db)
    
    # Phase 2: Process in batches
    job.status = ScanJobStatus.HASHING.value
    job.current_phase = "Processing files"
    await db.commit()
    
    new_count = 0
    updated_count = 0
    duplicate_count = 0
    excluded_count = 0
    error_count = 0
    
    for i in range(0, len(all_files), batch_size):
        batch = all_files[i:i + batch_size]
        
        for pdf_path, file_size in batch:
            job.current_file = str(pdf_path)
            job.processed_files += 1
            
            # Check exclusion rules
            should_exclude, matching_rule = exclusion_matcher.should_exclude(pdf_path, file_size)
            if should_exclude:
                if matching_rule:
                    await increment_rule_match(db, matching_rule.id)
                excluded_count += 1
                continue
            
            file_path_str = str(pdf_path)
            
            # Check if product exists
            existing_query = select(Product).where(Product.file_path == file_path_str)
            existing_result = await db.execute(existing_query)
            existing_product = existing_result.scalar_one_or_none()
            
            try:
                stat = pdf_path.stat()
                file_modified = datetime.fromtimestamp(stat.st_mtime)
                
                # Skip if unchanged
                if existing_product:
                    if existing_product.is_missing:
                        existing_product.is_missing = False
                        existing_product.missing_since = None
                    
                    if (
                        existing_product.file_size == file_size
                        and existing_product.file_modified_at
                        and existing_product.file_modified_at >= file_modified
                    ):
                        continue
                
                # Calculate hash
                file_hash = await calculate_file_hash(pdf_path)
                
                if existing_product:
                    if existing_product.file_hash == file_hash:
                        continue
                    
                    existing_product.file_size = file_size
                    existing_product.file_hash = file_hash
                    existing_product.file_modified_at = file_modified
                    existing_product.updated_at = datetime.now(UTC)
                    updated_count += 1
                    
                    if await check_and_mark_duplicate(db, existing_product):
                        duplicate_count += 1
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
                    await db.flush()
                    
                    if await check_and_mark_duplicate(db, product):
                        duplicate_count += 1
                    
                    new_count += 1
                    
            except Exception as e:
                logger.error(f"Error processing {pdf_path}: {e}")
                error_count += 1
        
        # Commit batch and update progress
        job.new_products = new_count
        job.updated_products = updated_count
        job.duplicates_found = duplicate_count
        job.excluded_files = excluded_count
        job.errors = error_count
        await db.commit()
        
        # Small delay to prevent overwhelming the system
        await asyncio.sleep(0.01)
    
    # Phase 3: Extract covers for new products
    job.status = ScanJobStatus.PROCESSING.value
    job.current_phase = "Extracting covers"
    await db.commit()
    
    from grimoire.services.processor import process_cover_sync
    
    # Get new products that need cover extraction
    new_products_query = select(Product).where(
        Product.watched_folder_id == folder.id,
        Product.cover_extracted == False,
        Product.is_duplicate == False,
    )
    result = await db.execute(new_products_query)
    products_needing_covers = list(result.scalars().all())
    
    for product in products_needing_covers:
        try:
            process_cover_sync(product)
        except Exception as e:
            logger.error(f"Error extracting cover for {product.file_name}: {e}")
    
    await db.commit()
    
    # Complete
    job.status = ScanJobStatus.COMPLETE.value
    job.current_phase = None
    job.current_file = None
    job.completed_at = datetime.now(UTC)
    await db.commit()
    
    logger.info(
        f"Scan complete: {new_count} new, {updated_count} updated, "
        f"{duplicate_count} duplicates, {excluded_count} excluded, {error_count} errors"
    )
    
    return {
        "status": "complete",
        "total_files": len(all_files),
        "new_products": new_count,
        "updated_products": updated_count,
        "duplicates_found": duplicate_count,
        "excluded_files": excluded_count,
        "errors": error_count,
    }


async def cancel_scan_job(db: AsyncSession, job_id: int) -> bool:
    """Cancel a running scan job."""
    job = await get_scan_job(db, job_id)
    if not job or not job.is_running:
        return False
    
    job.status = ScanJobStatus.CANCELLED.value
    job.completed_at = datetime.now(UTC)
    await db.commit()
    return True


async def get_scan_history(
    db: AsyncSession,
    limit: int = 10,
) -> list[ScanJob]:
    """Get recent scan jobs."""
    query = (
        select(ScanJob)
        .order_by(ScanJob.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())
