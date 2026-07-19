# backend/grimoire/processors/monster_segmenter.py
"""Heuristic segmentation of extracted bestiary pages into monster candidates.

High recall, sloppy precision: the LLM normalizer and human review gate sit
downstream, so emitting a bad candidate is cheap and missing one is not.
"""

import re
from dataclasses import dataclass

from grimoire.processors.system_profiles import SystemProfile

# A header-ish line: short, not ending in sentence punctuation, either markdown
# heading/bold or mostly capitalized words.
_MARKUP_RE = re.compile(r"^[#*_\s]+|[#*_\s]+$")
_HEADER_RE = re.compile(r"^(?:#{1,4}\s+|\*\*)?[A-Z][A-Za-z'\-]*(?:[\s,][A-Za-z'\-]+){0,5}(?:\*\*)?\s*$")

_MAX_LINES_ABOVE = 6      # how far above the anchor to look for a header
_MAX_LINES_BELOW = 15     # how far below the anchor a block may extend


@dataclass
class Candidate:
    name_guess: str
    page: int
    raw_text: str


def _clean_header(line: str) -> str:
    return _MARKUP_RE.sub("", line).strip()


def _is_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 60 or stripped.endswith((".", ",", ";", ":")):
        return False
    return bool(_HEADER_RE.match(stripped))


def segment_pages(pages: list[dict], profile: SystemProfile) -> list[Candidate]:
    """Find candidate monster entries in page-anchored markdown."""
    candidates: list[Candidate] = []
    for page_dict in pages:
        page_num = page_dict.get("page", 0)
        lines = (page_dict.get("markdown") or "").split("\n")
        text = "\n".join(lines)

        # Map anchor match positions to line indexes
        anchor_lines: list[int] = []
        for match in profile.statline_anchor.finditer(text):
            line_idx = text.count("\n", 0, match.start())
            if not anchor_lines or line_idx > anchor_lines[-1]:
                anchor_lines.append(line_idx)

        # Determine block boundaries per anchor
        starts: list[int] = []
        names: list[str] = []
        for anchor_idx in anchor_lines:
            start = max(0, anchor_idx - _MAX_LINES_ABOVE)
            name = ""
            for i in range(anchor_idx - 1, start - 1, -1):
                if _is_header(lines[i]):
                    start = i
                    name = _clean_header(lines[i])
                    break
            if not name:
                start = anchor_idx
                name = lines[anchor_idx].strip()[:40]
            starts.append(start)
            names.append(name)

        for pos, (start, anchor_idx) in enumerate(zip(starts, anchor_lines)):
            end = min(len(lines), anchor_idx + _MAX_LINES_BELOW)
            if pos + 1 < len(starts):
                end = min(end, starts[pos + 1])
            # Never let the next-candidate clip collapse this slice to empty:
            # high recall is load-bearing here (see module docstring), so a
            # candidate must never be silently discarded just because a later
            # anchor's header lookback lands on or before this one's start.
            end = max(start + 1, end)
            block = "\n".join(lines[start:end]).strip()
            if block:
                candidates.append(Candidate(name_guess=names[pos], page=page_num, raw_text=block))
    return candidates
