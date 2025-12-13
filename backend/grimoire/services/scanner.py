"""Library scanner service - scans folders for PDF files."""

import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Product, WatchedFolder


async def calculate_file_hash(file_path: Path) -> str:
    """Calculate SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def is_pdf_file(filename: str) -> bool:
    """Check if a file is a PDF based on extension."""
    return filename.lower().endswith(".pdf")


async def scan_folder(
    db: AsyncSession,
    folder: WatchedFolder,
    force: bool = False,
) -> list[Product]:
    """Scan a folder for PDF files and add them to the database.

    Args:
        db: Database session
        folder: The watched folder to scan
        force: If True, re-scan files even if they haven't changed

    Returns:
        List of newly added or updated products
    """
    folder_path = Path(folder.path)
    if not folder_path.exists():
        return []

    products = []

    for pdf_path in folder_path.rglob("*.pdf"):
        if not pdf_path.is_file():
            continue

        file_path_str = str(pdf_path)

        existing_query = select(Product).where(Product.file_path == file_path_str)
        existing_result = await db.execute(existing_query)
        existing_product = existing_result.scalar_one_or_none()

        stat = pdf_path.stat()
        file_size = stat.st_size
        file_modified = datetime.fromtimestamp(stat.st_mtime)

        if existing_product and not force:
            if (
                existing_product.file_size == file_size
                and existing_product.file_modified_at
                and existing_product.file_modified_at >= file_modified
            ):
                continue

        file_hash = await calculate_file_hash(pdf_path)

        if existing_product:
            if existing_product.file_hash == file_hash and not force:
                continue

            existing_product.file_size = file_size
            existing_product.file_hash = file_hash
            existing_product.file_modified_at = file_modified
            existing_product.updated_at = datetime.utcnow()
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

    await db.flush()

    from grimoire.services.processor import process_cover_sync

    for product in products:
        process_cover_sync(product)

    await db.commit()

    return products


async def remove_missing_products(db: AsyncSession, folder: WatchedFolder) -> int:
    """Remove products whose files no longer exist.

    Args:
        db: Database session
        folder: The watched folder to check

    Returns:
        Number of products removed
    """
    query = select(Product).where(Product.watched_folder_id == folder.id)
    result = await db.execute(query)
    products = result.scalars().all()

    removed = 0
    for product in products:
        if not Path(product.file_path).exists():
            await db.delete(product)
            removed += 1

    return removed
