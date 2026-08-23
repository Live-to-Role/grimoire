"""Watched folder API endpoints."""

import asyncio
import platform
import string
from datetime import datetime, UTC
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select

from grimoire.api.deps import DbSession
from grimoire.config import settings
from grimoire.utils.runtime import (
    CONTAINER_LIBRARY_PATHS,
    in_container,
    looks_like_container_library_path,
    looks_like_windows_path,
)
from grimoire.models import Product, WatchedFolder
from grimoire.schemas.folder import (
    BrowseResponse,
    DirectoryEntry,
    LibraryStats,
    QuickLocation,
    ScanRequest,
    ScanResponse,
    WatchedFolderCreate,
    WatchedFolderResponse,
    WatchedFolderUpdate,
)

router = APIRouter()


def _list_windows_drives() -> BrowseResponse:
    """List available drive letters on Windows.

    A: and B: are skipped: on machines with no floppy controller, probing them
    can block for seconds or pop a "no disk" dialog on the server's desktop.
    """
    directories = []
    for letter in string.ascii_uppercase[2:]:
        drive = Path(f"{letter}:\\")
        try:
            if drive.exists():
                directories.append(DirectoryEntry(name=f"{letter}:", path=str(drive)))
        except OSError:
            # Disconnected mapped drive — not available, but not an error either.
            continue
    return BrowseResponse(
        current_path="My Computer",
        parent_path=None,
        directories=directories,
        locations=_quick_locations(),
    )


def _default_browse_path() -> Path:
    """Where the browser opens when the client asks for no particular path.

    Home is the friendliest starting point on a desktop install. In a container
    it can be missing or unresolvable, so fall back rather than 500.
    """
    try:
        home = Path.home()
        if home.is_dir():
            return home
    except (RuntimeError, OSError):
        pass
    return Path(settings.library_path) if Path(settings.library_path).is_dir() else Path("/")


def _quick_locations() -> list[QuickLocation]:
    """Shortcuts to the directories worth starting from on this server.

    Under Docker the user's host paths do not exist inside the container; the
    mounted library roots are the only ones that do, and nothing in the UI
    would otherwise reveal them.
    """
    locations: list[QuickLocation] = []
    seen: set[str] = set()

    def add(name: str, candidate: Path) -> None:
        try:
            if not candidate.is_dir():
                return
        except OSError:
            return
        key = str(candidate)
        if key in seen:
            return
        seen.add(key)
        locations.append(QuickLocation(name=name, path=key))

    try:
        add("Home", Path.home())
    except (RuntimeError, OSError):
        pass

    add("Library", Path(settings.library_path))
    for extra in ("/library", "/library2", "/library3"):
        add(f"Mounted {extra}", Path(extra))

    if platform.system() == "Windows":
        add("This PC", Path(Path.home().anchor or "C:\\"))
    else:
        add("Filesystem root", Path("/"))

    return locations


@router.get("/browse", response_model=BrowseResponse)
async def browse_directories(path: str | None = Query(None, description="Directory path to browse")) -> BrowseResponse:
    """Browse server filesystem directories for folder selection.

    Every failure path returns a message naming the directory: "Select Folder"
    is the first thing a new user touches, and a bare "failed" tells neither
    them nor us whether the path is missing, unreadable, or off a dead mount.
    """
    is_windows = platform.system() == "Windows"

    # Special "My Computer" view to list all drives on Windows
    if path == "My Computer" and is_windows:
        return _list_windows_drives()

    if path:
        try:
            browse_path = Path(path).resolve()
        except OSError as e:
            raise HTTPException(status_code=400, detail=f"Cannot resolve {path}: {e.strerror or e}")
    else:
        browse_path = _default_browse_path()

    try:
        if not browse_path.exists():
            raise HTTPException(status_code=404, detail=f"{browse_path} does not exist on the server")
        if not browse_path.is_dir():
            raise HTTPException(status_code=400, detail=f"{browse_path} is not a directory")
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Cannot read {browse_path}: {e.strerror or e}")

    # Get parent path
    parent = browse_path.parent
    if parent == browse_path:
        # At filesystem root — on Windows, go up to drive list
        parent_path = "My Computer" if is_windows else None
    else:
        parent_path = str(parent)

    # List subdirectories, excluding hidden dirs
    directories = []
    skipped = 0
    try:
        entries = sorted(browse_path.iterdir(), key=lambda e: e.name.lower())
    except PermissionError:
        raise HTTPException(
            status_code=403, detail=f"Permission denied reading {browse_path}"
        )
    except OSError as e:
        raise HTTPException(
            status_code=400, detail=f"Cannot list {browse_path}: {e.strerror or e}"
        )

    for entry in entries:
        # One unreadable entry must not lose the other 200. Windows user
        # profiles carry deny-listed junctions ("Application Data", "Cookies");
        # network mounts can vanish between the listing and the stat.
        try:
            if entry.is_dir() and not entry.name.startswith('.'):
                directories.append(DirectoryEntry(name=entry.name, path=str(entry)))
        except OSError:
            skipped += 1

    return BrowseResponse(
        current_path=str(browse_path),
        parent_path=parent_path,
        directories=directories,
        locations=_quick_locations(),
        skipped=skipped,
    )


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
                is_source_of_truth=folder.is_source_of_truth,
                last_scanned_at=folder.last_scanned_at,
                created_at=folder.created_at,
                product_count=product_count,
            )
        )

    return responses


def _explain_missing_folder(path: str) -> str:
    """Say why the path is not there, in terms of the deployment in use.

    The commonest mistake is entering a path that belongs to the *other*
    deployment: `/library` exists only inside the Docker stack, and a Windows
    host path never exists inside it. Both come back as "does not exist", but
    the fix is the opposite in each case, so name it.
    """
    mounts = ", ".join(CONTAINER_LIBRARY_PATHS)

    if not in_container():
        if looks_like_container_library_path(path):
            return (
                f"{path} only exists inside the Docker stack, and Grimoire is running "
                "natively here. Enter the actual folder path on this machine instead — "
                r"for example C:\Users\you\Documents\RPG. PDF_LIBRARY_PATH in .env "
                "is read only by Docker Compose and has no effect on a native install."
            )
        return f"{path} does not exist on this machine"

    if looks_like_windows_path(path) or path.startswith(("/Users/", "/home/")):
        return (
            f"{path} is a path on your computer, and Grimoire is running inside Docker "
            f"where that path does not exist. Use the container path instead ({mounts}), "
            "and make sure PDF_LIBRARY_PATH in .env points at this folder."
        )

    if looks_like_container_library_path(path):
        return (
            f"{path} is not mounted in the container. Set PDF_LIBRARY_PATH in .env to "
            "the folder holding your PDFs, then recreate the stack with `docker compose "
            "-f docker/docker-compose.yml --project-directory . down` followed by `up -d` "
            "— bind mounts are fixed when the containers are created, so editing .env "
            "afterwards has no effect until they are recreated."
        )

    return f"{path} does not exist inside the container"


@router.post("", response_model=WatchedFolderResponse, status_code=201)
async def create_folder(db: DbSession, data: WatchedFolderCreate) -> WatchedFolderResponse:
    """Add a new watched folder."""
    folder_path = Path(data.path)
    if not folder_path.exists():
        raise HTTPException(status_code=400, detail=_explain_missing_folder(data.path))
    if not folder_path.is_dir():
        raise HTTPException(status_code=400, detail=f"{data.path} is not a directory")

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
        is_source_of_truth=folder.is_source_of_truth,
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
        is_source_of_truth=folder.is_source_of_truth,
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
    
    # If setting this folder as source of truth, clear others first
    if update_dict.get("is_source_of_truth") is True:
        clear_query = select(WatchedFolder).where(
            WatchedFolder.is_source_of_truth == True,
            WatchedFolder.id != folder_id
        )
        clear_result = await db.execute(clear_query)
        for other_folder in clear_result.scalars().all():
            other_folder.is_source_of_truth = False
    
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
        is_source_of_truth=folder.is_source_of_truth,
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
        folder.last_scanned_at = datetime.now(UTC)

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
            # Offload the CPU-heavy sync extraction (layout mode / OCR) to a
            # thread so it never blocks the event loop / other HTTP requests.
            if await asyncio.to_thread(
                process_text_extraction_sync, product, use_marker=use_marker
            ):
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

    def _split_facets(rows: list, split: bool = False) -> dict[str, int]:
        """Build facet counts, optionally splitting comma-separated values."""
        counts: dict[str, int] = {}
        for raw_value, count in rows:
            if raw_value is None:
                counts["Unknown"] = counts.get("Unknown", 0) + count
            elif split and ", " in raw_value:
                for part in raw_value.split(", "):
                    part = part.strip()
                    if part:
                        counts[part] = counts.get(part, 0) + count
            else:
                counts[raw_value] = counts.get(raw_value, 0) + count
        return counts

    system_query = select(Product.game_system, func.count()).group_by(Product.game_system)
    system_result = await db.execute(system_query)
    by_system = _split_facets(system_result.fetchall(), split=True)

    type_query = select(Product.product_type, func.count()).group_by(Product.product_type)
    type_result = await db.execute(type_query)
    by_type = _split_facets(type_result.fetchall())

    genre_query = select(Product.genre, func.count()).group_by(Product.genre)
    genre_result = await db.execute(genre_query)
    by_genre = _split_facets(genre_result.fetchall(), split=True)

    author_query = select(Product.author, func.count()).group_by(Product.author)
    author_result = await db.execute(author_query)
    by_author = _split_facets(author_result.fetchall(), split=True)

    publisher_query = select(Product.publisher, func.count()).group_by(Product.publisher)
    publisher_result = await db.execute(publisher_query)
    by_publisher = _split_facets(publisher_result.fetchall())

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
        by_genre=by_genre,
        by_author=by_author,
        by_publisher=by_publisher,
        processing_status={
            "pending": pending,
            "completed": completed,
            "failed": failed,
        },
    )
