"""
Map and image extraction from PDFs.
Extracts images, detects maps, and provides metadata.
"""

import io
import json
import logging
import os
import hashlib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class ExtractedImage:
    """An extracted image from a PDF."""
    index: int
    page: int
    width: int
    height: int
    format: str
    hash: str
    is_map: bool = False
    is_full_page: bool = False
    bbox: tuple[float, float, float, float] | None = None
    data: bytes | None = None

    def to_dict(self, include_data: bool = False) -> dict:
        result = {
            "index": self.index,
            "page": self.page,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "hash": self.hash,
            "is_map": self.is_map,
            "is_full_page": self.is_full_page,
            "aspect_ratio": round(self.width / self.height, 2) if self.height > 0 else 0,
        }
        if include_data and self.data:
            import base64
            result["data_base64"] = base64.b64encode(self.data).decode()
        return result


def is_likely_map(image: Image.Image, width: int, height: int) -> bool:
    """
    Heuristically determine if an image is likely a map.
    Maps tend to be:
    - Large (significant portion of page)
    - Roughly square or landscape
    - Have certain color characteristics
    """
    # Size check - maps are usually substantial
    if width < 200 or height < 200:
        return False

    # Aspect ratio - maps are rarely very tall/narrow
    aspect = width / height if height > 0 else 0
    if aspect < 0.5 or aspect > 3:
        return False

    # Size threshold - maps are usually large images
    if width * height < 100000:  # Less than ~316x316
        return False

    # Could add color analysis here:
    # - Maps often have earth tones, blues (water), greens (forests)
    # - High color diversity
    # - Grid patterns

    return True


def extract_images_from_page(
    doc: fitz.Document,
    page_num: int,
    min_width: int = 100,
    min_height: int = 100,
) -> list[ExtractedImage]:
    """Extract images from a single page."""
    images = []
    page = doc[page_num]
    page_rect = page.rect

    image_list = page.get_images(full=True)

    for img_index, img_info in enumerate(image_list):
        xref = img_info[0]

        try:
            base_image = doc.extract_image(xref)
            if not base_image:
                continue

            image_data = base_image["image"]
            image_ext = base_image["ext"]
            width = base_image["width"]
            height = base_image["height"]

            # Skip small images (likely icons, bullets, etc.)
            if width < min_width or height < min_height:
                continue

            # Calculate hash for deduplication
            img_hash = hashlib.md5(image_data).hexdigest()[:12]

            # Check if full page
            is_full = (
                width >= page_rect.width * 0.8 and
                height >= page_rect.height * 0.8
            )

            # Try to determine if it's a map
            try:
                pil_image = Image.open(io.BytesIO(image_data))
                is_map = is_likely_map(pil_image, width, height)
            except Exception:
                is_map = False

            images.append(ExtractedImage(
                index=len(images),
                page=page_num + 1,
                width=width,
                height=height,
                format=image_ext,
                hash=img_hash,
                is_map=is_map,
                is_full_page=is_full,
                data=image_data,
            ))

        except Exception as e:
            print(f"Error extracting image {xref}: {e}")
            continue

    return images


def extract_images_from_pdf(
    pdf_path: str | Path,
    start_page: int = 1,
    end_page: int | None = None,
    min_width: int = 100,
    min_height: int = 100,
    include_data: bool = False,
) -> list[ExtractedImage]:
    """
    Extract all images from a PDF.

    Args:
        pdf_path: Path to the PDF file
        start_page: Starting page (1-indexed)
        end_page: Ending page (1-indexed), None for all
        min_width: Minimum image width to include
        min_height: Minimum image height to include
        include_data: Whether to include raw image data

    Returns:
        List of ExtractedImage objects
    """
    images = []
    seen_hashes = set()

    doc = fitz.open(str(pdf_path))
    try:
        total_pages = len(doc)
        if end_page is None:
            end_page = total_pages

        for page_num in range(start_page - 1, min(end_page, total_pages)):
            page_images = extract_images_from_page(
                doc, page_num, min_width, min_height
            )

            for img in page_images:
                # Deduplicate by hash
                if img.hash in seen_hashes:
                    continue
                seen_hashes.add(img.hash)

                if not include_data:
                    img.data = None

                images.append(img)

    finally:
        doc.close()

    return images


def extract_maps_only(
    pdf_path: str | Path,
    start_page: int = 1,
    end_page: int | None = None,
) -> list[ExtractedImage]:
    """Extract only images that appear to be maps."""
    all_images = extract_images_from_pdf(
        pdf_path, start_page, end_page,
        min_width=200, min_height=200, include_data=True
    )
    return [img for img in all_images if img.is_map]


def save_images_to_directory(
    images: list[ExtractedImage],
    output_dir: str | Path,
    prefix: str = "image",
) -> list[str]:
    """
    Save extracted images to a directory.

    Returns list of saved file paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []

    for img in images:
        if not img.data:
            continue

        filename = f"{prefix}_{img.page:03d}_{img.index:02d}.{img.format}"
        filepath = output_dir / filename

        with open(filepath, "wb") as f:
            f.write(img.data)

        saved_paths.append(str(filepath))

    return saved_paths


def images_to_json(images: list[ExtractedImage], include_data: bool = False) -> list[dict]:
    """Convert images to JSON-serializable format."""
    return [img.to_dict(include_data) for img in images]


def extract_images(pdf_path: Path, output_dir: Path) -> dict:
    """
    Extract embedded images from a PDF and save to output directory.

    Creates a manifest.json with image metadata. Used by the gallery feature.

    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to save extracted images

    Returns:
        Dict with image_count, total_pages, and images list
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if not PYMUPDF_AVAILABLE:
        logger.error("PyMuPDF not available for image extraction")
        manifest = {"images": [], "image_count": 0, "total_pages": 0}
        _write_manifest(output_dir, manifest)
        return manifest

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    images = []
    image_index = 0

    for page_num, page in enumerate(doc):
        page_images = page.get_images(full=True)

        if page_images:
            for img_info in page_images:
                xref = img_info[0]
                try:
                    extracted = _extract_image_by_xref(doc, xref, output_dir, image_index)
                    if extracted:
                        extracted["page"] = page_num + 1
                        images.append(extracted)
                        image_index += 1
                except Exception as e:
                    logger.warning(f"Failed to extract image xref {xref} from page {page_num + 1}: {e}")
        else:
            extracted = _render_page(page, output_dir, image_index, page_num)
            if extracted:
                images.append(extracted)
                image_index += 1

    doc.close()

    manifest = {
        "images": images,
        "image_count": len(images),
        "total_pages": total_pages,
    }
    _write_manifest(output_dir, manifest)
    return manifest


def _extract_image_by_xref(doc, xref: int, output_dir: Path, index: int) -> dict | None:
    """Extract a single image by its xref and save as WebP."""
    base_image = doc.extract_image(xref)
    if not base_image or not base_image.get("image"):
        return None

    image_bytes = base_image["image"]
    width = base_image.get("width", 0)
    height = base_image.get("height", 0)
    original_ext = base_image.get("ext", "png")

    filename = f"{index + 1:03d}.webp"
    output_path = output_dir / filename

    if PIL_AVAILABLE:
        try:
            img = Image.open(BytesIO(image_bytes))
            img.save(str(output_path), "WEBP", quality=85)
        except Exception:
            filename = f"{index + 1:03d}.{original_ext}"
            output_path = output_dir / filename
            output_path.write_bytes(image_bytes)
    else:
        filename = f"{index + 1:03d}.{original_ext}"
        output_path = output_dir / filename
        output_path.write_bytes(image_bytes)

    return {
        "filename": filename,
        "width": width,
        "height": height,
        "original_format": original_ext,
        "file_size": output_path.stat().st_size,
    }


def _render_page(page, output_dir: Path, index: int, page_num: int) -> dict | None:
    """Render a page as an image (fallback when no embedded images found)."""
    try:
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        filename = f"{index + 1:03d}.webp"
        output_path = output_dir / filename

        if PIL_AVAILABLE:
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img.save(str(output_path), "WEBP", quality=85)
        else:
            filename = f"{index + 1:03d}.png"
            output_path = output_dir / filename
            pix.save(str(output_path))

        return {
            "filename": filename,
            "page": page_num + 1,
            "width": pix.width,
            "height": pix.height,
            "original_format": "rendered",
            "file_size": output_path.stat().st_size,
        }
    except Exception as e:
        logger.warning(f"Failed to render page {page_num + 1}: {e}")
        return None


def _write_manifest(output_dir: Path, manifest: dict) -> None:
    """Write the image manifest JSON file."""
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def get_image_stats(images: list[ExtractedImage]) -> dict:
    """Get statistics about extracted images."""
    if not images:
        return {
            "total": 0,
            "maps": 0,
            "full_page": 0,
            "formats": {},
        }

    formats = {}
    for img in images:
        formats[img.format] = formats.get(img.format, 0) + 1

    return {
        "total": len(images),
        "maps": sum(1 for img in images if img.is_map),
        "full_page": sum(1 for img in images if img.is_full_page),
        "formats": formats,
        "avg_width": sum(img.width for img in images) // len(images),
        "avg_height": sum(img.height for img in images) // len(images),
    }
