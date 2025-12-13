"""
Stat block detection and extraction from PDFs.
Detects monster/NPC stat blocks for various TTRPG systems.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber


@dataclass
class StatBlock:
    """A detected stat block."""
    name: str
    system: str  # e.g., "5e", "pf2e", "osr", "unknown"
    raw_text: str
    page: int
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "system": self.system,
            "page": self.page,
            "attributes": self.attributes,
            "raw_text": self.raw_text[:500] + "..." if len(self.raw_text) > 500 else self.raw_text,
        }


# D&D 5e stat block patterns
PATTERNS_5E = {
    "header": re.compile(r'^([A-Z][A-Za-z\s\'\-]+)\s*$'),
    "size_type": re.compile(r'^(Tiny|Small|Medium|Large|Huge|Gargantuan)\s+(aberration|beast|celestial|construct|dragon|elemental|fey|fiend|giant|humanoid|monstrosity|ooze|plant|undead)', re.IGNORECASE),
    "armor_class": re.compile(r'Armor Class\s*(\d+)', re.IGNORECASE),
    "hit_points": re.compile(r'Hit Points\s*(\d+)\s*\(([^)]+)\)', re.IGNORECASE),
    "speed": re.compile(r'Speed\s*(\d+\s*ft\.?)', re.IGNORECASE),
    "abilities": re.compile(r'STR\s+DEX\s+CON\s+INT\s+WIS\s+CHA', re.IGNORECASE),
    "ability_scores": re.compile(r'(\d{1,2})\s*\([+-]?\d+\)\s*(\d{1,2})\s*\([+-]?\d+\)\s*(\d{1,2})\s*\([+-]?\d+\)\s*(\d{1,2})\s*\([+-]?\d+\)\s*(\d{1,2})\s*\([+-]?\d+\)\s*(\d{1,2})\s*\([+-]?\d+\)'),
    "challenge": re.compile(r'Challenge\s*(\d+(?:/\d+)?)\s*\(([^)]+)\s*XP\)', re.IGNORECASE),
    "actions": re.compile(r'^Actions$', re.IGNORECASE | re.MULTILINE),
}

# Pathfinder 2e stat block patterns
PATTERNS_PF2E = {
    "header": re.compile(r'^([A-Z][A-Za-z\s\'\-]+)\s+Creature\s+(\d+)', re.IGNORECASE),
    "traits": re.compile(r'\[(Uncommon|Rare|Unique|[A-Z][a-z]+)\]', re.IGNORECASE),
    "perception": re.compile(r'Perception\s*\+(\d+)', re.IGNORECASE),
    "skills": re.compile(r'Skills\s+(.+)', re.IGNORECASE),
    "ac": re.compile(r'AC\s*(\d+)', re.IGNORECASE),
    "hp": re.compile(r'HP\s*(\d+)', re.IGNORECASE),
    "speed": re.compile(r'Speed\s*(\d+\s*feet)', re.IGNORECASE),
    "strike": re.compile(r'(Melee|Ranged)\s*\[', re.IGNORECASE),
}

# OSR/Basic stat block patterns
PATTERNS_OSR = {
    "header": re.compile(r'^([A-Z][A-Za-z\s\'\-]+)\s*$'),
    "hd": re.compile(r'HD[:\s]*(\d+(?:d\d+)?(?:[+-]\d+)?)', re.IGNORECASE),
    "ac": re.compile(r'AC[:\s]*(\d+)', re.IGNORECASE),
    "thac0": re.compile(r'THAC0[:\s]*(\d+)', re.IGNORECASE),
    "attacks": re.compile(r'(?:Att|Attacks?)[:\s]*(.+)', re.IGNORECASE),
    "damage": re.compile(r'(?:Dmg|Damage)[:\s]*(.+)', re.IGNORECASE),
    "save": re.compile(r'(?:Save|SV)[:\s]*([A-Z]\d+|\d+)', re.IGNORECASE),
    "morale": re.compile(r'(?:Morale|ML)[:\s]*(\d+)', re.IGNORECASE),
}


def detect_system(text: str) -> str:
    """Detect which game system a stat block belongs to."""
    text_lower = text.lower()

    # 5e indicators
    if 'challenge' in text_lower and 'xp)' in text_lower:
        if re.search(PATTERNS_5E["abilities"], text):
            return "5e"

    # PF2e indicators
    if re.search(r'creature\s+\d+', text_lower):
        if 'perception' in text_lower and 'strike' in text_lower:
            return "pf2e"

    # OSR indicators
    if re.search(r'\bthac0\b', text_lower) or re.search(r'\bmorale\b', text_lower):
        if re.search(r'\bhd\b', text_lower):
            return "osr"

    # Generic D&D-like
    if 'armor class' in text_lower and 'hit points' in text_lower:
        return "5e"

    return "unknown"


def parse_5e_statblock(text: str, name: str) -> dict[str, Any]:
    """Parse a 5e stat block into structured data."""
    attrs = {"name": name}

    # Size and type
    match = PATTERNS_5E["size_type"].search(text)
    if match:
        attrs["size"] = match.group(1)
        attrs["type"] = match.group(2)

    # AC
    match = PATTERNS_5E["armor_class"].search(text)
    if match:
        attrs["ac"] = int(match.group(1))

    # HP
    match = PATTERNS_5E["hit_points"].search(text)
    if match:
        attrs["hp"] = int(match.group(1))
        attrs["hit_dice"] = match.group(2)

    # Speed
    match = PATTERNS_5E["speed"].search(text)
    if match:
        attrs["speed"] = match.group(1)

    # Ability scores
    match = PATTERNS_5E["ability_scores"].search(text)
    if match:
        attrs["abilities"] = {
            "str": int(match.group(1)),
            "dex": int(match.group(2)),
            "con": int(match.group(3)),
            "int": int(match.group(4)),
            "wis": int(match.group(5)),
            "cha": int(match.group(6)),
        }

    # Challenge rating
    match = PATTERNS_5E["challenge"].search(text)
    if match:
        attrs["cr"] = match.group(1)
        attrs["xp"] = match.group(2)

    return attrs


def parse_pf2e_statblock(text: str, name: str) -> dict[str, Any]:
    """Parse a PF2e stat block into structured data."""
    attrs = {"name": name}

    # Level from header
    match = PATTERNS_PF2E["header"].search(text)
    if match:
        attrs["level"] = int(match.group(2))

    # Perception
    match = PATTERNS_PF2E["perception"].search(text)
    if match:
        attrs["perception"] = int(match.group(1))

    # AC
    match = PATTERNS_PF2E["ac"].search(text)
    if match:
        attrs["ac"] = int(match.group(1))

    # HP
    match = PATTERNS_PF2E["hp"].search(text)
    if match:
        attrs["hp"] = int(match.group(1))

    # Speed
    match = PATTERNS_PF2E["speed"].search(text)
    if match:
        attrs["speed"] = match.group(1)

    return attrs


def parse_osr_statblock(text: str, name: str) -> dict[str, Any]:
    """Parse an OSR stat block into structured data."""
    attrs = {"name": name}

    # HD
    match = PATTERNS_OSR["hd"].search(text)
    if match:
        attrs["hd"] = match.group(1)

    # AC
    match = PATTERNS_OSR["ac"].search(text)
    if match:
        attrs["ac"] = int(match.group(1))

    # THAC0
    match = PATTERNS_OSR["thac0"].search(text)
    if match:
        attrs["thac0"] = int(match.group(1))

    # Morale
    match = PATTERNS_OSR["morale"].search(text)
    if match:
        attrs["morale"] = int(match.group(1))

    return attrs


def is_statblock_start(line: str, next_lines: list[str]) -> tuple[bool, str | None]:
    """Check if a line starts a stat block."""
    line = line.strip()

    # Check for 5e style header followed by size/type
    if PATTERNS_5E["header"].match(line):
        for next_line in next_lines[:3]:
            if PATTERNS_5E["size_type"].search(next_line):
                return True, line

    # Check for PF2e style header
    match = PATTERNS_PF2E["header"].match(line)
    if match:
        return True, match.group(1)

    return False, None


def extract_statblock_text(lines: list[str], start_idx: int) -> tuple[str, int]:
    """Extract the full text of a stat block starting at start_idx."""
    text_lines = []
    end_idx = start_idx

    # Collect lines until we hit another header or significant whitespace
    for i in range(start_idx, min(start_idx + 100, len(lines))):
        line = lines[i]

        # Stop conditions
        if i > start_idx + 5:  # After initial lines
            # New stat block header
            if i + 3 < len(lines):
                is_new, _ = is_statblock_start(line, lines[i+1:i+4])
                if is_new:
                    break

            # Multiple blank lines
            if not line.strip() and i + 1 < len(lines) and not lines[i + 1].strip():
                break

        text_lines.append(line)
        end_idx = i

    return '\n'.join(text_lines), end_idx


def extract_statblocks_from_page(page, page_num: int) -> list[StatBlock]:
    """Extract stat blocks from a single page."""
    statblocks = []
    text = page.extract_text()

    if not text:
        return statblocks

    lines = text.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i]
        next_lines = lines[i+1:i+5] if i + 1 < len(lines) else []

        is_start, name = is_statblock_start(line, next_lines)

        if is_start and name:
            block_text, end_idx = extract_statblock_text(lines, i)
            system = detect_system(block_text)

            # Parse based on system
            if system == "5e":
                attrs = parse_5e_statblock(block_text, name)
            elif system == "pf2e":
                attrs = parse_pf2e_statblock(block_text, name)
            elif system == "osr":
                attrs = parse_osr_statblock(block_text, name)
            else:
                attrs = {"name": name}

            statblocks.append(StatBlock(
                name=name,
                system=system,
                raw_text=block_text,
                page=page_num,
                attributes=attrs,
            ))

            i = end_idx + 1
        else:
            i += 1

    return statblocks


def extract_statblocks_from_pdf(
    pdf_path: str | Path,
    start_page: int = 1,
    end_page: int | None = None,
    system_hint: str | None = None,
) -> list[StatBlock]:
    """
    Extract all stat blocks from a PDF.

    Args:
        pdf_path: Path to the PDF file
        start_page: Starting page (1-indexed)
        end_page: Ending page (1-indexed), None for all
        system_hint: Hint for which system to expect

    Returns:
        List of detected StatBlock objects
    """
    statblocks = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)
        if end_page is None:
            end_page = total_pages

        for page_num in range(start_page - 1, min(end_page, total_pages)):
            page = pdf.pages[page_num]
            page_blocks = extract_statblocks_from_page(page, page_num + 1)
            statblocks.extend(page_blocks)

    return statblocks


def statblocks_to_json(statblocks: list[StatBlock]) -> list[dict]:
    """Convert stat blocks to JSON-serializable format."""
    return [s.to_dict() for s in statblocks]


def statblocks_to_vtt(statblocks: list[StatBlock], vtt_format: str = "foundry") -> list[dict]:
    """
    Convert stat blocks to VTT-compatible format.
    Currently supports basic Foundry VTT format.
    """
    results = []

    for sb in statblocks:
        if vtt_format == "foundry" and sb.system == "5e":
            vtt_data = {
                "name": sb.name,
                "type": "npc",
                "system": {
                    "abilities": sb.attributes.get("abilities", {}),
                    "attributes": {
                        "ac": {"value": sb.attributes.get("ac")},
                        "hp": {
                            "value": sb.attributes.get("hp"),
                            "max": sb.attributes.get("hp"),
                            "formula": sb.attributes.get("hit_dice"),
                        },
                        "movement": {"walk": sb.attributes.get("speed", "").replace(" ft", "").replace(".", "")},
                    },
                    "details": {
                        "cr": sb.attributes.get("cr"),
                        "xp": {"value": sb.attributes.get("xp", "").replace(",", "")},
                        "type": {"value": sb.attributes.get("type")},
                    },
                },
            }
            results.append(vtt_data)
        else:
            # Generic format
            results.append(sb.to_dict())

    return results
