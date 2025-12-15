"""Library management API endpoints - scanning, stats, etc."""

from fastapi import APIRouter, HTTPException, BackgroundTasks
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
