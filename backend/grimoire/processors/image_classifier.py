"""Classify image-heavy PDFs as Map, Stock Art, Token, etc.

Detection strategy:
1. Filename/path keywords are the PRIMARY signal
2. Content analysis CONFIRMS (not triggers) — most pages must be image-dominant
3. For PDFs with no filename signal, only classify if overwhelmingly image-only
4. Never default to "Stock Art" — unknown content stays unclassified
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False


# Patterns checked against filename AND full path (case-insensitive)
_CLASSIFICATION_RULES = [
    ("Map", [
        r"\bmap\b", r"\bmaps\b", r"cartograph", r"battlemap", r"battle\s*map",
        r"dungeon\s*map", r"floorplan", r"floor\s*plan", r"overland\s*map",
        r"world\s*map", r"city\s*map", r"town\s*map", r"hex\s*map",
    ]),
    ("Token", [r"\btoken\b", r"\btokens\b", r"token\s*pack", r"token\s*set"]),
    ("Portrait", [r"\bportrait\b", r"\bportraits\b"]),
    ("Handout", [r"\bhandout\b", r"\bhandouts\b"]),
    ("Texture", [r"\btexture\b", r"\btextures\b"]),
    ("Stock Art", [
        r"stock\s*art", r"\bart\s*pack\b", r"clip\s*art",
        r"\bart\s*set\b", r"\bart\s*collection\b",
    ]),
]

# Words that strongly indicate this is a regular book, NOT image content
_BOOK_INDICATORS = [
    r"adventure", r"module", r"sourcebook", r"supplement",
    r"rulebook", r"manual", r"guide", r"companion",
    r"tome", r"volume", r"edition", r"gazetteer",
    r"bestiary", r"codex", r"compendium", r"campaign",
    r"setting", r"core.?rules?", r"player", r"master",
]


def classify_by_name(filename: str, file_path: str) -> str | None:
    """
    Check filename/path for image content keywords.

    Returns classification label if matched, None if no match.
    """
    search_text = f"{filename} {file_path}"

    for label, patterns in _CLASSIFICATION_RULES:
        for pattern in patterns:
            if re.search(pattern, search_text, re.IGNORECASE):
                return label

    return None


def _has_book_indicators(filename: str, file_path: str) -> bool:
    """Check if filename/path suggests this is a regular book."""
    search_text = f"{filename} {file_path}"
    for pattern in _BOOK_INDICATORS:
        if re.search(pattern, search_text, re.IGNORECASE):
            return True
    return False


def detect_image_content(
    pdf_path: str | Path,
    filename: str,
    file_path: str,
    max_sample_pages: int = 10,
    min_image_page_ratio: float = 0.8,
    max_chars_per_page: int = 50,
) -> dict:
    """
    Detect if a PDF is image content (maps, stock art, tokens, etc.).

    Two-tier detection:
    1. If filename/path matches known patterns AND content confirms → classify
    2. If no filename match, require overwhelming evidence (>90% pages near-zero text)

    Args:
        pdf_path: Path to the PDF file
        filename: The PDF filename
        file_path: Full path string for heuristic matching
        max_sample_pages: Max pages to sample for content analysis
        min_image_page_ratio: Fraction of sampled pages that must be image-dominant
        max_chars_per_page: Max filtered chars for a page to count as "image-dominant"

    Returns:
        Dictionary with:
        - is_image_content: bool
        - classification: str | None (Map, Stock Art, etc.)
        - reason: str
        - stats: dict with analysis details
    """
    name_classification = classify_by_name(filename, file_path)
    is_book = _has_book_indicators(filename, file_path)

    # If it looks like a book by name, don't classify as image content
    # even if the name also matches (e.g. "Adventure Map Guide" is a book)
    if is_book and not name_classification:
        return {
            "is_image_content": False,
            "classification": None,
            "reason": f"Filename suggests regular book",
            "stats": {},
        }

    # Content analysis
    content = _analyze_content(pdf_path, max_sample_pages, max_chars_per_page)
    if content is None:
        return {
            "is_image_content": False,
            "classification": None,
            "reason": "Could not analyze content",
            "stats": {},
        }

    image_page_ratio = content["image_dominant_pages"] / content["pages_sampled"] if content["pages_sampled"] > 0 else 0

    if name_classification:
        # Filename matches — use relaxed content threshold
        # Even if a map pack has a few text pages (credits, license), it should still qualify
        if is_book and image_page_ratio < 0.5:
            # Name matches both book AND image content patterns, but content is mostly text
            return {
                "is_image_content": False,
                "classification": None,
                "reason": f"Filename matches '{name_classification}' but content is mostly text ({image_page_ratio:.0%} image pages)",
                "stats": content,
            }
        # For name-matched files, require at least 50% image-dominant pages
        if image_page_ratio >= 0.5:
            return {
                "is_image_content": True,
                "classification": name_classification,
                "reason": f"Filename matches '{name_classification}' with {image_page_ratio:.0%} image-dominant pages",
                "stats": content,
            }
        else:
            return {
                "is_image_content": False,
                "classification": None,
                "reason": f"Filename matches '{name_classification}' but only {image_page_ratio:.0%} image-dominant pages",
                "stats": content,
            }
    else:
        # No filename match — require overwhelming evidence
        if image_page_ratio >= 0.9 and content["avg_chars_per_page"] < 20:
            return {
                "is_image_content": True,
                "classification": None,  # Can't determine type without name signal
                "reason": f"Overwhelmingly image-based ({image_page_ratio:.0%} image pages, {content['avg_chars_per_page']:.0f} avg chars/page)",
                "stats": content,
            }
        else:
            return {
                "is_image_content": False,
                "classification": None,
                "reason": f"No filename signal, content not conclusive ({image_page_ratio:.0%} image pages, {content['avg_chars_per_page']:.0f} avg chars/page)",
                "stats": content,
            }


def _analyze_content(
    pdf_path: str | Path,
    max_sample_pages: int,
    max_chars_per_page: int,
) -> dict | None:
    """Analyze PDF content for image-dominance across sampled pages."""
    if not PYMUPDF_AVAILABLE:
        return None

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return None

    try:
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        pages_to_check = min(max_sample_pages, total_pages)

        total_text_chars = 0
        image_dominant_pages = 0
        total_images = 0

        # Sample pages spread across the document, not just the first few
        if total_pages <= max_sample_pages:
            page_indices = list(range(total_pages))
        else:
            # Evenly spaced sample across the document
            step = total_pages / max_sample_pages
            page_indices = [int(i * step) for i in range(max_sample_pages)]

        for i in page_indices:
            page = doc[i]

            # Get text content
            text = page.get_text().strip()
            # Filter out watermarks
            filtered_text = re.sub(r'[\w.+-]+@[\w-]+\.[\w.-]+', '', text)
            filtered_text = re.sub(r'Transaction:\s*\d+', '', filtered_text)
            filtered_text = re.sub(r'\s+', '', filtered_text)

            char_count = len(filtered_text)
            total_text_chars += char_count

            # Check for images
            image_list = page.get_images(full=True)
            total_images += len(image_list)

            # Page is "image-dominant" if very little text and has images
            if char_count <= max_chars_per_page and len(image_list) > 0:
                image_dominant_pages += 1

        doc.close()

        return {
            "total_pages": total_pages,
            "pages_sampled": len(page_indices),
            "image_dominant_pages": image_dominant_pages,
            "total_images": total_images,
            "total_text_chars": total_text_chars,
            "avg_chars_per_page": total_text_chars / len(page_indices) if page_indices else 0,
        }

    except Exception as e:
        logger.warning(f"Content analysis failed for {pdf_path}: {e}")
        return None
