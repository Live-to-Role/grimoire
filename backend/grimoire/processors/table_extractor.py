"""
Random table detection and extraction from PDFs.
Detects rollable tables (d6, d20, d100, etc.) common in TTRPG products.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber


@dataclass
class TableEntry:
    """A single entry in a random table."""
    roll: str  # e.g., "1", "1-2", "01-05"
    result: str
    sub_entries: list["TableEntry"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "roll": self.roll,
            "result": self.result,
            "sub_entries": [e.to_dict() for e in self.sub_entries],
        }


@dataclass
class RandomTable:
    """A detected random table."""
    title: str
    die_type: str  # e.g., "d6", "d20", "d100", "2d6"
    entries: list[TableEntry]
    page: int
    source_text: str | None = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "die_type": self.die_type,
            "entries": [e.to_dict() for e in self.entries],
            "page": self.page,
            "entry_count": len(self.entries),
        }

    def to_rollable(self) -> dict:
        """Convert to a format suitable for rolling."""
        return {
            "title": self.title,
            "die": self.die_type,
            "results": {e.roll: e.result for e in self.entries},
        }


# Patterns for detecting random tables
DIE_PATTERNS = [
    re.compile(r'\b(d4)\b', re.IGNORECASE),
    re.compile(r'\b(d6)\b', re.IGNORECASE),
    re.compile(r'\b(d8)\b', re.IGNORECASE),
    re.compile(r'\b(d10)\b', re.IGNORECASE),
    re.compile(r'\b(d12)\b', re.IGNORECASE),
    re.compile(r'\b(d20)\b', re.IGNORECASE),
    re.compile(r'\b(d100)\b', re.IGNORECASE),
    re.compile(r'\b(d%)\b', re.IGNORECASE),
    re.compile(r'\b(2d6)\b', re.IGNORECASE),
    re.compile(r'\b(3d6)\b', re.IGNORECASE),
    re.compile(r'\b(1d6)\b', re.IGNORECASE),
    re.compile(r'\b(1d20)\b', re.IGNORECASE),
]

# Pattern for table title lines
TABLE_TITLE_PATTERNS = [
    re.compile(r'^(.+?)\s*\(?(d\d+|d%|[123]d\d+)\)?[:\s]*$', re.IGNORECASE),
    re.compile(r'^(random\s+.+?)\s*table', re.IGNORECASE),
    re.compile(r'^(.+?)\s+table\s*\(?(d\d+|d%)\)?', re.IGNORECASE),
    re.compile(r'^roll\s+(d\d+|d%|[123]d\d+)\s*[:\-]?\s*(.+)?', re.IGNORECASE),
]

# Pattern for table entry lines
ENTRY_PATTERNS = [
    # "1. Result" or "1) Result"
    re.compile(r'^(\d+)[\.\)]\s+(.+)$'),
    # "1-2 Result" or "1–2 Result" (en-dash)
    re.compile(r'^(\d+[\-–]\d+)\s+(.+)$'),
    # "01-05 Result" (d100 style)
    re.compile(r'^(\d{2}[\-–]\d{2})\s+(.+)$'),
    # "1: Result"
    re.compile(r'^(\d+):\s+(.+)$'),
    # Just "1 Result" with number at start
    re.compile(r'^(\d{1,3})\s{2,}(.+)$'),
]


def detect_die_type(text: str) -> str | None:
    """Detect the die type mentioned in text."""
    for pattern in DIE_PATTERNS:
        match = pattern.search(text)
        if match:
            die = match.group(1).lower()
            # Normalize d% to d100
            if die == 'd%':
                return 'd100'
            return die
    return None


def parse_table_entries(lines: list[str], expected_die: str | None = None) -> list[TableEntry]:
    """Parse lines into table entries."""
    entries = []
    current_entry = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Try to match entry patterns
        matched = False
        for pattern in ENTRY_PATTERNS:
            match = pattern.match(line)
            if match:
                roll = match.group(1)
                result = match.group(2).strip()

                # Validate roll makes sense
                if '-' in roll or '–' in roll:
                    # Range like "1-2" or "01-05"
                    parts = re.split(r'[\-–]', roll)
                    if len(parts) == 2:
                        try:
                            start, end = int(parts[0]), int(parts[1])
                            if start <= end:
                                current_entry = TableEntry(roll=roll, result=result)
                                entries.append(current_entry)
                                matched = True
                                break
                        except ValueError:
                            continue
                else:
                    # Single number
                    try:
                        num = int(roll)
                        if 1 <= num <= 100:
                            current_entry = TableEntry(roll=roll, result=result)
                            entries.append(current_entry)
                            matched = True
                            break
                    except ValueError:
                        continue

        # If no match and we have a current entry, this might be continuation
        if not matched and current_entry and line and not line[0].isdigit():
            current_entry.result += " " + line

    return entries


def validate_table(entries: list[TableEntry], die_type: str | None) -> bool:
    """Validate that entries form a coherent random table."""
    if len(entries) < 2:
        return False

    # Check if entries cover expected range
    if die_type:
        die_max = {
            'd4': 4, 'd6': 6, 'd8': 8, 'd10': 10,
            'd12': 12, 'd20': 20, 'd100': 100,
            '1d6': 6, '2d6': 12, '3d6': 18,
            '1d20': 20,
        }.get(die_type.lower())

        if die_max:
            # Check if we have roughly the right number of entries
            # Allow some flexibility for ranges
            if len(entries) > die_max * 2:
                return False

    return True


def extract_tables_from_page(page, page_num: int) -> list[RandomTable]:
    """Extract random tables from a single page."""
    tables = []
    text = page.extract_text()

    if not text:
        return tables

    lines = text.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Look for table title
        title = None
        die_type = None

        for pattern in TABLE_TITLE_PATTERNS:
            match = pattern.match(line)
            if match:
                groups = match.groups()
                if len(groups) >= 1:
                    title = groups[0].strip() if groups[0] else None
                if len(groups) >= 2 and groups[1]:
                    die_type = groups[1].lower()
                    if die_type == 'd%':
                        die_type = 'd100'
                break

        # Also check if line contains a die reference
        if not die_type:
            die_type = detect_die_type(line)

        if die_type and not title:
            # Use the line as title if it's short enough
            if len(line) < 100:
                title = line

        if title and die_type:
            # Collect following lines as potential entries
            entry_lines = []
            j = i + 1

            while j < len(lines) and j < i + 50:  # Limit search
                entry_line = lines[j].strip()

                # Stop if we hit another table title or empty section
                if not entry_line:
                    # Allow one blank line
                    if j + 1 < len(lines) and not lines[j + 1].strip():
                        break
                    j += 1
                    continue

                # Check if this looks like a new section
                if any(p.match(entry_line) for p in TABLE_TITLE_PATTERNS):
                    break

                entry_lines.append(entry_line)
                j += 1

            # Try to parse entries
            entries = parse_table_entries(entry_lines, die_type)

            if validate_table(entries, die_type):
                tables.append(RandomTable(
                    title=title,
                    die_type=die_type,
                    entries=entries,
                    page=page_num,
                    source_text='\n'.join([line] + entry_lines[:20]),
                ))
                i = j
                continue

        i += 1

    return tables


def extract_tables_from_pdf(
    pdf_path: str | Path,
    start_page: int = 1,
    end_page: int | None = None,
) -> list[RandomTable]:
    """
    Extract all random tables from a PDF.

    Args:
        pdf_path: Path to the PDF file
        start_page: Starting page (1-indexed)
        end_page: Ending page (1-indexed), None for all

    Returns:
        List of detected RandomTable objects
    """
    tables = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)
        if end_page is None:
            end_page = total_pages

        for page_num in range(start_page - 1, min(end_page, total_pages)):
            page = pdf.pages[page_num]
            page_tables = extract_tables_from_page(page, page_num + 1)
            tables.extend(page_tables)

    return tables


def extract_tables_with_ai(
    text: str,
    provider: str | None = None,
) -> list[dict]:
    """
    Use AI to extract tables from text when pattern matching fails.
    Returns structured table data.
    """
    # Placeholder for AI-based extraction
    # Would use a prompt like:
    # "Extract any random/rollable tables from this text. Return JSON with title, die_type, and entries."
    return []


def tables_to_json(tables: list[RandomTable]) -> list[dict]:
    """Convert tables to JSON-serializable format."""
    return [t.to_dict() for t in tables]


def tables_to_rollable(tables: list[RandomTable]) -> list[dict]:
    """Convert tables to rollable format for VTT export."""
    return [t.to_rollable() for t in tables]
