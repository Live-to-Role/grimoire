"""Watched folder API endpoints."""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select

from grimoire.api.deps import DbSession
from grimoire.models import Product, WatchedFolder
from grimoire.schemas.folder import (
    LibraryStats,
    ScanRequest,
    ScanResponse,
    WatchedFolderCreate,
    WatchedFolderResponse,
    WatchedFolderUpdate,
)

router = APIRouter()


@router.get("", response_model=list[WatchedFolderResponse])
async def list_folders(db: DbSession) -> list[WatchedFolderResponse]:
    """List all watched folders."""
    query = select(WatchedFolder).order_by(WatchedFolder.label, WatchedFolder.path)
    result = await db.execute(query)
    folders = result.scalars().all()

    responses = []
    for folder in folders:
        count_query = select(func.count()).where(Product.watched_folder_id == folder.id)
        count_result = await db.execute(count_query)
        product_count = count_result.scalar() or 0

        responses.append(
            WatchedFolderResponse(
                id=folder.id,
                path=folder.path,
                label=folder.label,
                enabled=folder.enabled,
                last_scanned_at=folder.last_scanned_at,
                created_at=folder.created_at,
                product_count=product_count,
            )
        )

    return responses


@router.post("", response_model=WatchedFolderResponse, status_code=201)
async def create_folder(db: DbSession, data: WatchedFolderCreate) -> WatchedFolderResponse:
    """Add a new watched folder."""
    folder_path = Path(data.path)
    if not folder_path.exists():
        raise HTTPException(status_code=400, detail="Folder path does not exist")
    if not folder_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    existing = await db.execute(select(WatchedFolder).where(WatchedFolder.path == data.path))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Folder already being watched")

    folder = WatchedFolder(
        path=data.path,
        label=data.label,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)

    return WatchedFolderResponse(
        id=folder.id,
        path=folder.path,
        label=folder.label,
        enabled=folder.enabled,
        last_scanned_at=folder.last_scanned_at,
        created_at=folder.created_at,
        product_count=0,
    )


@router.get("/{folder_id}", response_model=WatchedFolderResponse)
async def get_folder(db: DbSession, folder_id: int) -> WatchedFolderResponse:
    """Get a single watched folder."""
    query = select(WatchedFolder).where(WatchedFolder.id == folder_id)
    result = await db.execute(query)
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    count_query = select(func.count()).where(Product.watched_folder_id == folder.id)
    count_result = await db.execute(count_query)
    product_count = count_result.scalar() or 0

    return WatchedFolderResponse(
        id=folder.id,
        path=folder.path,
        label=folder.label,
        enabled=folder.enabled,
        last_scanned_at=folder.last_scanned_at,
        created_at=folder.created_at,
        product_count=product_count,
    )


@router.patch("/{folder_id}", response_model=WatchedFolderResponse)
async def update_folder(
    db: DbSession, folder_id: int, data: WatchedFolderUpdate
) -> WatchedFolderResponse:
    """Update a watched folder."""
    query = select(WatchedFolder).where(WatchedFolder.id == folder_id)
    result = await db.execute(query)
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    update_dict = data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(folder, field, value)

    await db.commit()
    await db.refresh(folder)

    count_query = select(func.count()).where(Product.watched_folder_id == folder.id)
    count_result = await db.execute(count_query)
    product_count = count_result.scalar() or 0

    return WatchedFolderResponse(
        id=folder.id,
        path=folder.path,
        label=folder.label,
        enabled=folder.enabled,
        last_scanned_at=folder.last_scanned_at,
        created_at=folder.created_at,
        product_count=product_count,
    )


@router.delete("/{folder_id}", status_code=204)
async def delete_folder(
    db: DbSession,
    folder_id: int,
    remove_products: bool = Query(False, description="Also remove products from this folder"),
) -> Response:
    """Remove a watched folder."""
    query = select(WatchedFolder).where(WatchedFolder.id == folder_id)
    result = await db.execute(query)
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    if remove_products:
        products_query = select(Product).where(Product.watched_folder_id == folder_id)
        products_result = await db.execute(products_query)
        products = products_result.scalars().all()
        for product in products:
            await db.delete(product)
    else:
        await db.execute(
            select(Product)
            .where(Product.watched_folder_id == folder_id)
            .execution_options(synchronize_session="fetch")
        )

    await db.delete(folder)
    await db.commit()

    return Response(status_code=204)


@router.post("/scan", response_model=ScanResponse)
async def scan_library(db: DbSession, request: ScanRequest) -> ScanResponse:
    """Trigger a library scan."""
    if request.folder_id:
        query = select(WatchedFolder).where(
            WatchedFolder.id == request.folder_id, WatchedFolder.enabled == True
        )
        result = await db.execute(query)
        folder = result.scalar_one_or_none()
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found or disabled")
        folders = [folder]
    else:
        query = select(WatchedFolder).where(WatchedFolder.enabled == True)
        result = await db.execute(query)
        folders = result.scalars().all()

    if not folders:
        return ScanResponse(message="No folders to scan", folders_queued=0)

    from grimoire.services.scanner import scan_folder

    for folder in folders:
        await scan_folder(db, folder, force=request.force)
        folder.last_scanned_at = datetime.utcnow()

    await db.commit()

    return ScanResponse(
        message=f"Scan completed for {len(folders)} folder(s)",
        folders_queued=len(folders),
    )


@router.post("/library/extract-all")
async def extract_all_text(
    db: DbSession,
    use_marker: bool = Query(False, description="Use Marker for better quality (slower)"),
    force: bool = Query(False, description="Re-extract even if already extracted"),
) -> dict:
    """Extract text from all products that haven't been processed yet."""
    from grimoire.services.processor import process_text_extraction_sync

    if force:
        query = select(Product)
    else:
        query = select(Product).where(Product.text_extracted == False)

    result = await db.execute(query)
    products = result.scalars().all()

    total = len(products)
    success = 0
    failed = 0

    for product in products:
        try:
            if process_text_extraction_sync(product, use_marker=use_marker):
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"Error extracting {product.file_name}: {e}")
            failed += 1

    await db.commit()

    return {
        "message": f"Batch extraction completed",
        "total": total,
        "success": success,
        "failed": failed,
    }


@router.get("/library/stats", response_model=LibraryStats)
async def get_library_stats(db: DbSession) -> LibraryStats:
    """Get library statistics."""
    total_query = select(func.count()).select_from(Product)
    total_result = await db.execute(total_query)
    total_products = total_result.scalar() or 0

    pages_query = select(func.coalesce(func.sum(Product.page_count), 0))
    pages_result = await db.execute(pages_query)
    total_pages = pages_result.scalar() or 0

    size_query = select(func.coalesce(func.sum(Product.file_size), 0))
    size_result = await db.execute(size_query)
    total_size = size_result.scalar() or 0

    system_query = select(Product.game_system, func.count()).group_by(Product.game_system)
    system_result = await db.execute(system_query)
    by_system = {row[0] or "Unknown": row[1] for row in system_result.fetchall()}

    type_query = select(Product.product_type, func.count()).group_by(Product.product_type)
    type_result = await db.execute(type_query)
    by_type = {row[0] or "Unknown": row[1] for row in type_result.fetchall()}

    from grimoire.models import ProcessingQueue

    pending_query = select(func.count()).where(ProcessingQueue.status == "pending")
    pending_result = await db.execute(pending_query)
    pending = pending_result.scalar() or 0

    completed_query = select(func.count()).where(ProcessingQueue.status == "completed")
    completed_result = await db.execute(completed_query)
    completed = completed_result.scalar() or 0

    failed_query = select(func.count()).where(ProcessingQueue.status == "failed")
    failed_result = await db.execute(failed_query)
    failed = failed_result.scalar() or 0

    return LibraryStats(
        total_products=total_products,
        total_pages=total_pages,
        total_size_bytes=total_size,
        by_system=by_system,
        by_type=by_type,
        processing_status={
            "pending": pending,
            "completed": completed,
            "failed": failed,
        },
    )
