"""Duplicate management API endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from grimoire.api.deps import DbSession
from grimoire.services.duplicate_service import (
    get_duplicate_groups,
    get_duplicate_stats,
    scan_for_duplicates,
    resolve_duplicate,
    bulk_delete_duplicates,
    delete_all_duplicates_in_group,
    preview_duplicate_resolution,
    resolve_duplicates_with_source_of_truth,
    get_deleted_duplicates,
    clear_deleted_duplicate,
    clear_all_deleted_duplicates,
)

router = APIRouter()


class ResolveDuplicateRequest(BaseModel):
    """Request to resolve a duplicate."""
    action: str  # 'keep', 'remove_record', 'mark_canonical'


class BulkDeleteRequest(BaseModel):
    """Request to bulk delete duplicates."""
    product_ids: list[int]
    delete_files: bool = False  # If True, also delete files from disk


@router.get("")
async def list_duplicate_groups(db: DbSession) -> dict:
    """Get all groups of duplicate files."""
    groups = await get_duplicate_groups(db)
    return {
        "groups": groups,
        "total_groups": len(groups),
    }


@router.get("/stats")
async def duplicate_stats(db: DbSession) -> dict:
    """Get duplicate statistics."""
    return await get_duplicate_stats(db)


@router.post("/scan")
async def scan_duplicates(db: DbSession) -> dict:
    """Scan library for duplicates and mark them."""
    return await scan_for_duplicates(db)


@router.post("/{product_id}/resolve")
async def resolve_product_duplicate(
    db: DbSession,
    product_id: int,
    request: ResolveDuplicateRequest,
) -> dict:
    """Resolve a duplicate product."""
    result = await resolve_duplicate(db, product_id, request.action)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
    return result


@router.post("/bulk-delete")
async def bulk_delete(db: DbSession, request: BulkDeleteRequest) -> dict:
    """Delete multiple duplicate products at once."""
    result = await bulk_delete_duplicates(
        db, 
        request.product_ids, 
        delete_files=request.delete_files
    )
    return result


@router.post("/group/{file_hash}/delete-duplicates")
async def delete_group_duplicates(
    db: DbSession,
    file_hash: str,
    delete_files: bool = False,
) -> dict:
    """Delete all duplicates in a group, keeping only the canonical."""
    result = await delete_all_duplicates_in_group(db, file_hash, delete_files=delete_files)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
    return result


class ResolveWithSourceOfTruthRequest(BaseModel):
    """Request to resolve duplicates using source of truth rules."""
    delete_files: bool = False


@router.get("/resolve/preview")
async def preview_resolution(db: DbSession) -> dict:
    """
    Preview what would happen if duplicates were resolved using source of truth rules.
    
    Rules:
    1. If a duplicate exists in source of truth folder, keep that version
    2. Otherwise, keep the newest version (by file_modified_at)
    """
    return await preview_duplicate_resolution(db)


@router.post("/resolve/execute")
async def execute_resolution(
    db: DbSession,
    request: ResolveWithSourceOfTruthRequest,
) -> dict:
    """
    Execute duplicate resolution using source of truth rules.
    
    Rules:
    1. If a duplicate exists in source of truth folder, keep that version
    2. Otherwise, keep the newest version (by file_modified_at)
    """
    result = await resolve_duplicates_with_source_of_truth(db, delete_files=request.delete_files)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
    return result


@router.get("/deleted")
async def list_deleted_duplicates(db: DbSession) -> dict:
    """Get list of file paths that were deleted as duplicates and won't be re-imported."""
    deleted = await get_deleted_duplicates(db)
    return {
        "deleted_duplicates": [
            {
                "id": d.id,
                "file_path": d.file_path,
                "file_hash": d.file_hash,
                "original_product_id": d.original_product_id,
                "deleted_at": d.deleted_at.isoformat() if d.deleted_at else None,
            }
            for d in deleted
        ],
        "total": len(deleted),
    }


class ClearDeletedDuplicateRequest(BaseModel):
    """Request to clear a deleted duplicate tracking entry."""
    file_path: str


@router.post("/deleted/clear")
async def clear_deleted(db: DbSession, request: ClearDeletedDuplicateRequest) -> dict:
    """Remove a path from deleted duplicates list, allowing it to be re-imported on next scan."""
    success = await clear_deleted_duplicate(db, request.file_path)
    if not success:
        raise HTTPException(status_code=404, detail="Deleted duplicate not found")
    return {"success": True, "file_path": request.file_path}


@router.post("/deleted/clear-all")
async def clear_all_deleted(db: DbSession) -> dict:
    """Clear all deleted duplicate tracking, allowing all files to be re-imported."""
    count = await clear_all_deleted_duplicates(db)
    return {"success": True, "cleared": count}
