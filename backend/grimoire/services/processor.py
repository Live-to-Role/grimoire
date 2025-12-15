"""PDF processing service - extracts covers, metadata, and text."""

import json
from pathlib import Path

import fitz
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.config import settings
from grimoire.models import ProcessingQueue, Product


async def queue_cover_extraction(db: AsyncSession, product: Product) -> ProcessingQueue | None:
    """Queue a cover extraction task for a product."""
    if product.cover_extracted:
        return None

    queue_item = ProcessingQueue(
        product_id=product.id,
        task_type="cover",
        priority=3,
        status="pending",
    )
    db.add(queue_item)
    await db.flush()
    return queue_item


def extract_cover_image(pdf_path: Path, output_path: Path, size: int = 300) -> bool:
    """Extract the first page of a PDF as a cover image.

    Args:
        pdf_path: Path to the PDF file
        output_path: Path to save the cover image
        size: Maximum dimension for the thumbnail

    Returns:
        True if successful, False otherwise
    """
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            return False

        page = doc[0]

        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        img.thumbnail((size, size * 4 // 3), Image.Resampling.LANCZOS)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, "JPEG", quality=85, optimize=True)

        doc.close()
        return True

    except Exception as e:
        print(f"Error extracting cover from {pdf_path}: {e}")
        return False


def extract_pdf_metadata(pdf_path: Path) -> dict:
    """Extract metadata from a PDF file.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Dictionary with metadata
    """
    try:
        doc = fitz.open(pdf_path)

        metadata = {
            "page_count": len(doc),
            "title": doc.metadata.get("title"),
            "author": doc.metadata.get("author"),
            "subject": doc.metadata.get("subject"),
            "keywords": doc.metadata.get("keywords"),
            "creator": doc.metadata.get("creator"),
            "producer": doc.metadata.get("producer"),
        }

        doc.close()
        return metadata

    except Exception as e:
        print(f"Error extracting metadata from {pdf_path}: {e}")
        return {"page_count": None}


def process_cover_sync(product: Product) -> bool:
    """Process cover extraction synchronously (updates product in place).

    Args:
        product: The product to process

    Returns:
        True if successful, False otherwise
    """
    from grimoire.services.metadata_extractor import extract_all_metadata, apply_metadata_to_product
    
    pdf_path = Path(product.file_path)
    if not pdf_path.exists():
        return False

    cover_filename = f"{product.id}.jpg"
    cover_path = settings.covers_dir / cover_filename

    success = extract_cover_image(pdf_path, cover_path, settings.cover_thumbnail_size)

    if success:
        product.cover_image_path = str(cover_path)
        product.cover_extracted = True

        # Extract comprehensive metadata from PDF, text, and filename
        metadata = extract_all_metadata(pdf_path)
        apply_metadata_to_product(product, metadata, overwrite=False)

    return success


async def process_cover_task(db: AsyncSession, product: Product) -> bool:
    """Process a cover extraction task (async version).

    Args:
        db: Database session
        product: The product to process

    Returns:
        True if successful, False otherwise
    """
    success = process_cover_sync(product)
    if success:
        await db.commit()
    return success


def process_text_extraction_sync(product: Product, use_marker: bool = False) -> bool:
    """Extract text from a PDF and save to file.

    Args:
        product: The product to process
        use_marker: Use Marker for extraction (slower but better quality)

    Returns:
        True if successful, False otherwise
    """
    import json
    from grimoire.processors.text_extractor import extract_text_to_markdown

    pdf_path = Path(product.file_path)
    if not pdf_path.exists():
        return False

    result = extract_text_to_markdown(
        pdf_path,
        use_marker=use_marker,
        use_pymupdf=True,
        include_page_numbers=True,
        include_page_breaks=True,
        filter_headers_footers=True,
    )

    if "error" in result:
        print(f"Text extraction failed for {product.file_name}: {result['error']}")
        return False

    text_dir = settings.data_dir / "text"
    text_dir.mkdir(parents=True, exist_ok=True)

    text_file = text_dir / f"{product.id}.json"
    with open(text_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    product.extracted_text_path = str(text_file)
    product.text_extracted = True

    return True


async def process_text_task(db: AsyncSession, product: Product, use_marker: bool = False) -> bool:
    """Process text extraction task (async version).

    Args:
        db: Database session
        product: The product to process
        use_marker: Use Marker for extraction

    Returns:
        True if successful, False otherwise
    """
    success = process_text_extraction_sync(product, use_marker)
    if success:
        await db.commit()
    return success


def get_extracted_text(product: Product) -> str | None:
    """Get the extracted text for a product.

    Args:
        product: The product to get text for

    Returns:
        The extracted markdown text or None if not available
    """
    import json

    if not product.text_extracted or not product.extracted_text_path:
        return None

    text_path = Path(product.extracted_text_path)
    if not text_path.exists():
        return None

    try:
        with open(text_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("markdown")
    except Exception:
        return None
