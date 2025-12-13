"""
Table of Contents extraction from PDFs.
Detects and parses TOC structures for navigation and content organization.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False


@dataclass
class TOCEntry:
    """A single entry in the table of contents."""
    title: str
    page: int | None = None
    level: int = 1
    children: list["TOCEntry"] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "page": self.page,
            "level": self.level,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class TOCResult:
    """Result of TOC extraction."""
    entries: list[TOCEntry]
    method: str
    toc_pages: list[int] | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "entries": [e.to_dict() for e in self.entries],
            "method": self.method,
            "toc_pages": self.toc_pages,
            "entry_count": len(self.entries),
        }

    def flatten(self) -> list[dict]:
        """Flatten TOC to a simple list."""
        result = []

        def _flatten(entries: list[TOCEntry], parent_path: str = ""):
            for entry in entries:
                path = f"{parent_path}/{entry.title}" if parent_path else entry.title
                result.append({
                    "title": entry.title,
                    "page": entry.page,
                    "level": entry.level,
                    "path": path,
                })
                _flatten(entry.children, path)

        _flatten(self.entries)
        return result


def extract_toc_from_outline(pdf_path: str | Path) -> TOCResult | None:
    """
    Extract TOC from PDF outline/bookmarks (embedded metadata).
    This is the most reliable method when available.
    """
    if not PYMUPDF_AVAILABLE:
        return None

    try:
        doc = fitz.open(str(pdf_path))
        toc = doc.get_toc()
        doc.close()

        if not toc:
            return None

        entries = []
        stack: list[tuple[int, TOCEntry]] = []

        for level, title, page in toc:
            entry = TOCEntry(
                title=title.strip(),
                page=page if page > 0 else None,
                level=level,
            )

            # Find parent based on level
            while stack and stack[-1][0] >= level:
                stack.pop()

            if stack:
                stack[-1][1].children.append(entry)
            else:
                entries.append(entry)

            stack.append((level, entry))

        return TOCResult(entries=entries, method="outline")

    except Exception as e:
        print(f"Outline extraction failed: {e}")
        return None


def extract_toc_from_text(pdf_path: str | Path, max_pages: int = 10) -> TOCResult | None:
    """
    Extract TOC by parsing text content.
    Looks for common TOC patterns in the first few pages.
    """
    # Patterns for TOC entries
    # Format: "Chapter Title ... 42" or "Chapter Title....42" or "Chapter Title 42"
    toc_line_pattern = re.compile(
        r'^(.+?)\s*[\.·…\-_]{2,}\s*(\d+)\s*$|'  # With dots/dashes
        r'^(.+?)\s{3,}(\d+)\s*$|'  # With multiple spaces
        r'^(\d+[\.\)]\s+.+?)\s+(\d+)\s*$'  # Numbered: "1. Chapter ... 42"
    )

    # Patterns that indicate we're in a TOC section
    toc_header_patterns = [
        re.compile(r'^(table\s+of\s+)?contents?$', re.IGNORECASE),
        re.compile(r'^index$', re.IGNORECASE),
        re.compile(r'^chapters?$', re.IGNORECASE),
    ]

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            entries = []
            toc_pages = []
            in_toc = False
            consecutive_non_toc = 0

            for page_num in range(min(max_pages, len(pdf.pages))):
                page = pdf.pages[page_num]
                text = page.extract_text()

                if not text:
                    continue

                lines = text.split('\n')
                page_has_toc = False

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Check for TOC header
                    for pattern in toc_header_patterns:
                        if pattern.match(line):
                            in_toc = True
                            page_has_toc = True
                            break

                    if not in_toc:
                        continue

                    # Try to match TOC entry
                    match = toc_line_pattern.match(line)
                    if match:
                        groups = match.groups()
                        # Find the non-None groups
                        title = None
                        page_ref = None
                        for i in range(0, len(groups), 2):
                            if groups[i] is not None:
                                title = groups[i].strip()
                                page_ref = int(groups[i + 1])
                                break

                        if title and page_ref:
                            # Determine level based on indentation or numbering
                            level = 1
                            if re.match(r'^\s{4,}', line):
                                level = 2
                            elif re.match(r'^\s{8,}', line):
                                level = 3

                            entries.append(TOCEntry(
                                title=title,
                                page=page_ref,
                                level=level,
                            ))
                            page_has_toc = True
                            consecutive_non_toc = 0

                if page_has_toc:
                    toc_pages.append(page_num + 1)
                elif in_toc:
                    consecutive_non_toc += 1
                    if consecutive_non_toc > 1:
                        # Probably left the TOC section
                        break

            if entries:
                return TOCResult(
                    entries=entries,
                    method="text_parsing",
                    toc_pages=toc_pages,
                )

    except Exception as e:
        print(f"Text TOC extraction failed: {e}")

    return None


def extract_toc_with_ai(
    pdf_path: str | Path,
    text_sample: str,
    provider: str | None = None,
) -> TOCResult | None:
    """
    Extract TOC using AI analysis of text content.
    Useful when TOC format is non-standard.
    """
    # This would call the AI identifier with a specific prompt
    # For now, return None - can be implemented later
    return None


def extract_toc(pdf_path: str | Path) -> TOCResult:
    """
    Extract table of contents from a PDF using the best available method.

    Priority:
    1. PDF outline/bookmarks (most reliable)
    2. Text parsing (common patterns)
    3. Empty result if nothing found
    """
    pdf_path = Path(pdf_path)

    # Try outline first
    result = extract_toc_from_outline(pdf_path)
    if result and result.entries:
        return result

    # Try text parsing
    result = extract_toc_from_text(pdf_path)
    if result and result.entries:
        return result

    # Return empty result
    return TOCResult(entries=[], method="none")


def get_chapter_boundaries(toc: TOCResult) -> list[dict]:
    """
    Get page boundaries for each chapter/section.
    Useful for splitting content by chapter.
    """
    flat = toc.flatten()
    if not flat:
        return []

    boundaries = []
    for i, entry in enumerate(flat):
        if entry["page"] is None:
            continue

        next_page = None
        for j in range(i + 1, len(flat)):
            if flat[j]["page"] is not None:
                next_page = flat[j]["page"] - 1
                break

        boundaries.append({
            "title": entry["title"],
            "start_page": entry["page"],
            "end_page": next_page,
            "level": entry["level"],
        })

    return boundaries
