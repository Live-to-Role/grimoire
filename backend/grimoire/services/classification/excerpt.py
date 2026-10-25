"""Build the ~4k-token excerpt the classifier reads instead of the whole book.

The head (cover, credits, contents, introduction) is where type and levels are
usually stated; level windows catch the statement when it sits deeper. Spell,
caster, and dungeon levels are filtered out so they do not spend the windows.
"""

import re
from dataclasses import dataclass

from grimoire.models.classification import CodexProduct

_CHARS_PER_TOKEN = 4

LEVEL_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\blevels? \d+(\s*(-|–|to|through)\s*\d+)?",
        r"\b\d+(st|nd|rd|th)[ -]level",
        r"\b0-level",
        r"\blevel 0\b",
        r"\bfunnel",
        r"\bcharacter levels?",
        r"\bcharacters? of level",
        r"\btiers? \d",
    )
]

_NEGATIVE_CONTEXT = re.compile(
    r"spell|caster|dungeon level|"
    r"level \d+ (warlock|wizard|cleric|druid|sorcerer|bard|paladin|ranger)",
    re.IGNORECASE,
)
_CONTEXT_CHARS = 40


@dataclass
class Excerpt:
    text: str
    source: str
    windows: int
    unpaged: bool
    tokens: int


def estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


@dataclass
class _Unit:
    """A page (or, unpaged, the whole text) the head and windows are cut from."""

    tag: str  # "page" or "offset"
    number: int
    text: str


@dataclass
class _Window:
    unit: int  # index into units
    start: int
    end: int


def _level_hits(text: str) -> list[tuple[int, int]]:
    hits = []
    for pattern in LEVEL_PATTERNS:
        for m in pattern.finditer(text):
            context = text[max(0, m.start() - _CONTEXT_CHARS): m.end() + _CONTEXT_CHARS]
            if not _NEGATIVE_CONTEXT.search(context):
                hits.append((m.start(), m.end()))
    return sorted(hits)


def _windows(units: list[_Unit], head_chars: list[int], window_chars: int) -> list[_Window]:
    """Merged windows around level hits not already shown in the head, earliest first."""
    found: list[_Window] = []
    for i, unit in enumerate(units):
        for start, end in _level_hits(unit.text):
            if start < head_chars[i]:
                continue
            centre = (start + end) // 2
            w = _Window(
                i,
                max(head_chars[i], centre - window_chars // 2),
                min(len(unit.text), centre + window_chars // 2),
            )
            if found and found[-1].unit == i and w.start <= found[-1].end:
                found[-1].end = max(found[-1].end, w.end)
            else:
                found.append(w)
    return found


def _render(header: dict[str, str], units: list[_Unit], head_chars: list[int],
            windows: list[_Window]) -> str:
    parts = ["# Document"]
    parts += [f"{k}: {v}" for k, v in header.items()]
    parts.append("\n# Opening pages")
    for unit, n in zip(units, head_chars):
        if n:
            parts.append(f"--- {unit.tag} {unit.number if unit.tag == 'page' else 0} ---")
            parts.append(unit.text[:n].strip())
    if windows:
        parts.append("\n# Passages mentioning levels")
        for w in windows:
            unit = units[w.unit]
            number = unit.number if unit.tag == "page" else w.start
            parts.append(f"--- {unit.tag} {number} ---")
            parts.append(unit.text[w.start:w.end].strip())
    return "\n".join(parts) + "\n"


def build_excerpt(
    text_json: dict,
    header: dict[str, str],
    head_tokens: int = 2500,
    window_tokens: int = 150,
    max_windows: int = 6,
    max_tokens: int = 4000,
) -> Excerpt:
    pages = text_json.get("pages")
    unpaged = not pages
    if unpaged:
        units = [_Unit("offset", 0, text_json.get("markdown") or "")]
    else:
        units = [_Unit("page", p.get("page", i + 1), p.get("markdown") or "")
                 for i, p in enumerate(pages)]

    # Head: whole pages from the start until the budget; the page that would
    # overflow is cut to what is left.
    head_chars = [0] * len(units)
    budget = head_tokens * _CHARS_PER_TOKEN
    for i, unit in enumerate(units):
        if budget <= 0:
            break
        head_chars[i] = min(len(unit.text), budget)
        budget -= head_chars[i] + 20  # the page tag line

    windows = _windows(units, head_chars, window_tokens * _CHARS_PER_TOKEN)[:max_windows]

    # Hard cap: trim the head from its end first, then drop windows from the last.
    text = _render(header, units, head_chars, windows)
    while estimate_tokens(text) > max_tokens:
        excess = (estimate_tokens(text) - max_tokens) * _CHARS_PER_TOKEN + _CHARS_PER_TOKEN
        last = max((i for i, n in enumerate(head_chars) if n), default=None)
        if last is not None:
            head_chars[last] = max(0, head_chars[last] - excess)
        elif windows:
            windows.pop()
        else:
            break
        text = _render(header, units, head_chars, windows)

    return Excerpt(text, "pdf", len(windows), unpaged, estimate_tokens(text))


def build_description_excerpt(codex: CodexProduct, max_tokens: int = 4000) -> Excerpt:
    """Excerpt for a Codex product with no Grimoire file: title, publisher, blurb."""
    header = {
        "title": codex.title,
        "publisher": codex.publisher or "",
        "page_count": "" if codex.page_count is None else str(codex.page_count),
    }
    lines = ["# Document"] + [f"{k}: {v}" for k, v in header.items()]
    text = "\n".join(lines) + "\n\n# Description\n"
    room = max(0, max_tokens * _CHARS_PER_TOKEN - len(text) - 1)
    text += (codex.description or "")[:room] + "\n"
    return Excerpt(text, "description", 0, False, estimate_tokens(text))
