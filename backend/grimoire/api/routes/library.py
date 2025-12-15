"""Library management API endpoints - scanning, stats, etc."""

import json
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, func

from grimoire.api.deps import DbSession
from grimoire.models import Product, WatchedFolder, ScanJob, ScanJobStatus
from grimoire.services.batch_scanner import (
    create_scan_job,
    get_active_scan_job,
    get_scan_job,
    batch_scan_folder,
    cancel_scan_job,
    get_scan_history,
)
from grimoire.worker.tasks import scan_folder_task

router = APIRouter()


class ScanRequest(BaseModel):
    """Request to start a library scan."""
    folder_id: int | None = None  # None = scan all folders
    batch_size: int = 100


@router.get("/stats")
async def library_stats(db: DbSession) -> dict:
    """Get library statistics."""
    # Total products
    total_query = select(func.count(Product.id))
    total_result = await db.execute(total_query)
    total_products = total_result.scalar() or 0
    
    # Total size
    size_query = select(func.sum(Product.file_size))
    size_result = await db.execute(size_query)
    total_size = size_result.scalar() or 0
    
    # Duplicates
    dup_query = select(func.count(Product.id)).where(Product.is_duplicate == True)
    dup_result = await db.execute(dup_query)
    duplicate_count = dup_result.scalar() or 0
    
    # Missing
    missing_query = select(func.count(Product.id)).where(Product.is_missing == True)
    missing_result = await db.execute(missing_query)
    missing_count = missing_result.scalar() or 0
    
    # Excluded
    excluded_query = select(func.count(Product.id)).where(Product.is_excluded == True)
    excluded_result = await db.execute(excluded_query)
    excluded_count = excluded_result.scalar() or 0
    
    # Processing status
    cover_query = select(func.count(Product.id)).where(Product.cover_extracted == True)
    cover_result = await db.execute(cover_query)
    covers_extracted = cover_result.scalar() or 0
    
    text_query = select(func.count(Product.id)).where(Product.text_extracted == True)
    text_result = await db.execute(text_query)
    text_extracted = text_result.scalar() or 0
    
    ai_query = select(func.count(Product.id)).where(Product.ai_identified == True)
    ai_result = await db.execute(ai_query)
    ai_identified = ai_result.scalar() or 0
    
    return {
        "total_products": total_products,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "total_size_gb": round(total_size / (1024 * 1024 * 1024), 2),
        "duplicates": duplicate_count,
        "missing": missing_count,
        "excluded": excluded_count,
        "processing": {
            "covers_extracted": covers_extracted,
            "text_extracted": text_extracted,
            "ai_identified": ai_identified,
        },
    }


@router.get("/scan/status")
async def scan_status(db: DbSession) -> dict:
    """Get status of current or most recent scan."""
    job = await get_active_scan_job(db)
    
    if not job:
        # Get most recent completed job
        history = await get_scan_history(db, limit=1)
        if history:
            job = history[0]
        else:
            return {"status": "idle", "message": "No scans have been run"}
    
    return {
        "id": job.id,
        "status": job.status,
        "current_phase": job.current_phase,
        "current_file": job.current_file,
        "progress": {
            "total_files": job.total_files,
            "processed_files": job.processed_files,
            "percent": job.progress_percent,
        },
        "results": {
            "new_products": job.new_products,
            "updated_products": job.updated_products,
            "duplicates_found": job.duplicates_found,
            "excluded_files": job.excluded_files,
            "errors": job.errors,
        },
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "is_running": job.is_running,
    }


@router.post("/scan")
async def start_scan(
    db: DbSession,
    background_tasks: BackgroundTasks,
    request: ScanRequest | None = None,
) -> dict:
    """Start a library scan."""
    # Check for existing running scan
    existing = await get_active_scan_job(db)
    if existing:
        raise HTTPException(
            status_code=409,
            detail="A scan is already in progress"
        )
    
    folder_id = request.folder_id if request else None
    batch_size = request.batch_size if request else 100
    
    # Get folder(s) to scan
    if folder_id:
        folder_query = select(WatchedFolder).where(WatchedFolder.id == folder_id)
        folder_result = await db.execute(folder_query)
        folder = folder_result.scalar_one_or_none()
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        folders = [folder]
    else:
        folder_query = select(WatchedFolder).where(WatchedFolder.enabled == True)
        folder_result = await db.execute(folder_query)
        folders = list(folder_result.scalars().all())
    
    if not folders:
        raise HTTPException(status_code=400, detail="No folders to scan")
    
    # Create scan job
    job = await create_scan_job(db, folder_id)
    
    # Trigger the scan task for each folder
    for folder in folders:
        scan_folder_task(folder.id)
    
    return {
        "job_id": job.id,
        "status": "started",
        "folders": [{"id": f.id, "path": f.path} for f in folders],
        "message": f"Scan started for {len(folders)} folder(s)",
    }


@router.post("/scan/{job_id}/cancel")
async def cancel_scan(db: DbSession, job_id: int) -> dict:
    """Cancel a running scan."""
    success = await cancel_scan_job(db, job_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Scan not found or not running"
        )
    return {"cancelled": True, "job_id": job_id}


@router.get("/scan/history")
async def scan_history(db: DbSession, limit: int = 10) -> dict:
    """Get scan history."""
    jobs = await get_scan_history(db, limit)
    return {
        "jobs": [
            {
                "id": j.id,
                "status": j.status,
                "total_files": j.total_files,
                "new_products": j.new_products,
                "duplicates_found": j.duplicates_found,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in jobs
        ],
        "total": len(jobs),
    }


@router.post("/reextract-metadata")
async def reextract_metadata(
    db: DbSession,
    limit: int = 100,
    force: bool = False,
) -> dict:
    """Re-extract metadata for products that are missing it.
    
    Args:
        limit: Maximum number of products to process
        force: If True, re-extract even if metadata exists
    """
    from pathlib import Path
    from grimoire.services.metadata_extractor import extract_all_metadata, apply_metadata_to_product
    
    # Find products needing metadata extraction
    if force:
        query = select(Product).where(
            Product.is_duplicate == False,
            Product.is_missing == False,
        ).limit(limit)
    else:
        # Products with no game_system or genre
        query = select(Product).where(
            Product.is_duplicate == False,
            Product.is_missing == False,
            (Product.game_system.is_(None)) | (Product.genre.is_(None)),
        ).limit(limit)
    
    result = await db.execute(query)
    products = list(result.scalars().all())
    
    processed = 0
    updated = 0
    errors = []
    
    for product in products:
        try:
            pdf_path = Path(product.file_path)
            if not pdf_path.exists():
                errors.append(f"{product.file_name}: File not found")
                continue
            
            metadata = extract_all_metadata(pdf_path)
            changes = apply_metadata_to_product(product, metadata, overwrite=force)
            
            if changes:
                updated += 1
            processed += 1
            
        except Exception as e:
            errors.append(f"{product.file_name}: {str(e)}")
    
    await db.commit()
    
    return {
        "processed": processed,
        "updated": updated,
        "errors_count": len(errors),
        "errors": errors[:10],  # First 10 errors
        "message": f"Processed {processed} products, updated {updated}",
    }


@router.get("/filters")
async def get_filter_options(db: DbSession) -> dict:
    """Get available filter options for the library sidebar.
    
    Returns distinct values for game_system, genre, product_type, publisher, and author
    along with counts for each value.
    """
    # Game systems with counts
    game_systems_query = (
        select(Product.game_system, func.count(Product.id).label("count"))
        .where(Product.is_duplicate == False, Product.is_missing == False)
        .group_by(Product.game_system)
        .order_by(func.count(Product.id).desc())
    )
    game_systems_result = await db.execute(game_systems_query)
    game_systems = [
        {"value": row[0] or "Unknown", "count": row[1]}
        for row in game_systems_result.all()
    ]
    
    # Genres with counts
    genres_query = (
        select(Product.genre, func.count(Product.id).label("count"))
        .where(Product.is_duplicate == False, Product.is_missing == False, Product.genre.isnot(None))
        .group_by(Product.genre)
        .order_by(func.count(Product.id).desc())
    )
    genres_result = await db.execute(genres_query)
    genres = [
        {"value": row[0], "count": row[1]}
        for row in genres_result.all()
    ]
    
    # Product types with counts
    product_types_query = (
        select(Product.product_type, func.count(Product.id).label("count"))
        .where(Product.is_duplicate == False, Product.is_missing == False, Product.product_type.isnot(None))
        .group_by(Product.product_type)
        .order_by(func.count(Product.id).desc())
    )
    product_types_result = await db.execute(product_types_query)
    product_types = [
        {"value": row[0], "count": row[1]}
        for row in product_types_result.all()
    ]
    
    # Publishers with counts (top 50)
    publishers_query = (
        select(Product.publisher, func.count(Product.id).label("count"))
        .where(Product.is_duplicate == False, Product.is_missing == False, Product.publisher.isnot(None))
        .group_by(Product.publisher)
        .order_by(func.count(Product.id).desc())
        .limit(50)
    )
    publishers_result = await db.execute(publishers_query)
    publishers = [
        {"value": row[0], "count": row[1]}
        for row in publishers_result.all()
    ]
    
    # Authors with counts (top 50)
    authors_query = (
        select(Product.author, func.count(Product.id).label("count"))
        .where(Product.is_duplicate == False, Product.is_missing == False, Product.author.isnot(None))
        .group_by(Product.author)
        .order_by(func.count(Product.id).desc())
        .limit(50)
    )
    authors_result = await db.execute(authors_query)
    authors = [
        {"value": row[0], "count": row[1]}
        for row in authors_result.all()
    ]
    
    return {
        "game_systems": game_systems,
        "genres": genres,
        "product_types": product_types,
        "publishers": publishers,
        "authors": authors,
    }


@router.post("/import/dtrpg")
async def import_dtrpg_library(
    db: DbSession,
    file: UploadFile = File(...),
    apply: bool = True,
    limit: int | None = None,
) -> dict:
    """Import DriveThruRPG library JSON and match to local products.
    
    Upload the JSON from: https://www.drivethrurpg.com/api/products/mylibrary/search?show_all=1&...
    
    Args:
        file: DTRPG library JSON file
        apply: If True, update products with matched metadata
        limit: Maximum number of products to process
    """
    from grimoire.services.dtrpg_import import import_dtrpg_library as do_import
    
    try:
        content = await file.read()
        json_data = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    
    try:
        result = await do_import(db, json_data=json_data, apply=apply, limit=limit)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/import/dtrpg/stats")
async def get_dtrpg_stats_endpoint(
    file: UploadFile = File(...),
) -> dict:
    """Get statistics about a DTRPG library export without importing.
    
    Useful for previewing what will be imported.
    """
    from grimoire.services.dtrpg_import import get_dtrpg_stats
    
    try:
        content = await file.read()
        json_data = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    
    try:
        return get_dtrpg_stats(json_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
