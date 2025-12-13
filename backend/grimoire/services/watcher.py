"""File watcher service - monitors folders for new/changed PDFs."""

import asyncio
from pathlib import Path
from typing import Callable

from watchfiles import awatch, Change

from grimoire.config import settings


class LibraryWatcher:
    """Watches library folders for file changes."""

    def __init__(self, on_change: Callable[[Path, Change], None]):
        """Initialize the watcher.

        Args:
            on_change: Callback function called when a file changes.
                       Receives (path, change_type) arguments.
        """
        self.on_change = on_change
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self, paths: list[str]) -> None:
        """Start watching the specified paths.

        Args:
            paths: List of directory paths to watch
        """
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._watch(paths))

    async def stop(self) -> None:
        """Stop the watcher."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _watch(self, paths: list[str]) -> None:
        """Internal watch loop."""
        watch_paths = [p for p in paths if Path(p).exists()]
        if not watch_paths:
            return

        async for changes in awatch(*watch_paths, recursive=True):
            if not self._running:
                break

            for change_type, path_str in changes:
                path = Path(path_str)

                if not path.suffix.lower() == ".pdf":
                    continue

                try:
                    self.on_change(path, change_type)
                except Exception as e:
                    print(f"Error handling file change {path}: {e}")


async def handle_file_change(path: Path, change_type: Change) -> None:
    """Handle a file change event.

    Args:
        path: Path to the changed file
        change_type: Type of change (added, modified, deleted)
    """
    from sqlalchemy import select

    from grimoire.database import async_session_maker
    from grimoire.models import Product, WatchedFolder
    from grimoire.services.scanner import calculate_file_hash
    from grimoire.services.processor import process_cover_sync

    async with async_session_maker() as db:
        if change_type == Change.deleted:
            result = await db.execute(
                select(Product).where(Product.file_path == str(path))
            )
            product = result.scalar_one_or_none()
            if product:
                await db.delete(product)
                await db.commit()
                print(f"Removed deleted file: {path.name}")
            return

        folder_query = select(WatchedFolder).where(WatchedFolder.enabled == True)
        folder_result = await db.execute(folder_query)
        folders = folder_result.scalars().all()

        matching_folder = None
        for folder in folders:
            if str(path).startswith(folder.path):
                matching_folder = folder
                break

        if not matching_folder:
            return

        existing = await db.execute(
            select(Product).where(Product.file_path == str(path))
        )
        product = existing.scalar_one_or_none()

        stat = path.stat()
        file_hash = await calculate_file_hash(path)

        if product:
            if product.file_hash != file_hash:
                product.file_size = stat.st_size
                product.file_hash = file_hash
                process_cover_sync(product)
                await db.commit()
                print(f"Updated modified file: {path.name}")
        else:
            product = Product(
                file_path=str(path),
                file_name=path.name,
                file_size=stat.st_size,
                file_hash=file_hash,
                watched_folder_id=matching_folder.id,
                title=path.stem,
            )
            db.add(product)
            await db.flush()
            process_cover_sync(product)
            await db.commit()
            print(f"Added new file: {path.name}")


watcher: LibraryWatcher | None = None


async def start_watcher() -> None:
    """Start the global file watcher."""
    global watcher

    from sqlalchemy import select
    from grimoire.database import async_session_maker
    from grimoire.models import WatchedFolder

    async with async_session_maker() as db:
        result = await db.execute(
            select(WatchedFolder).where(WatchedFolder.enabled == True)
        )
        folders = result.scalars().all()
        paths = [f.path for f in folders]

    if not paths:
        print("No watched folders configured, file watcher not started")
        return

    def sync_handler(path: Path, change: Change) -> None:
        asyncio.create_task(handle_file_change(path, change))

    watcher = LibraryWatcher(sync_handler)
    await watcher.start(paths)
    print(f"File watcher started for {len(paths)} folder(s)")


async def stop_watcher() -> None:
    """Stop the global file watcher."""
    global watcher
    if watcher:
        await watcher.stop()
        watcher = None
        print("File watcher stopped")
