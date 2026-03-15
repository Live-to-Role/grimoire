"""Revision detection service — identifies products that are revisions of each other."""

import re
from pathlib import Path

# Trailing format tags to strip (case-insensitive)
FORMAT_TAGS = [
    r"[-_]PDF",
]

# Trailing revision patterns to strip (case-insensitive)
# Order matters: longer/more specific patterns first
REVISION_PATTERNS = [
    r"\(Print[_ ]Friendly\)",
    r"[-_]2nd[_ ]Edition",
    r"[-_]3rd[_ ]Edition",
    r"[-_]Revised",
    r"\(Revised\)",
    r"[-_]Updated",
    r"\(Updated\)",
    r"[-_]Errata",
    r"\(Errata\)",
    r"[-_]Final",
    r"\(Final\)",
    r"[-_]v\d+(?:\.\d+)?",  # _v2, _v1.2
]

# Combined pattern for detecting if a filename has any revision indicator (trailing only)
_REVISION_DETECT_RE = re.compile(
    r"(?:" + "|".join(REVISION_PATTERNS) + r")\s*$",
    re.IGNORECASE,
)

# Build a single regex that strips trailing format tags and revision patterns
# Apply iteratively since a filename may have both (e.g., "Adventure-PDF_(Revised)")
_FORMAT_TAG_RE = re.compile(
    r"(?:" + "|".join(FORMAT_TAGS) + r")\s*$",
    re.IGNORECASE,
)
_REVISION_PATTERN_RE = re.compile(
    r"(?:" + "|".join(REVISION_PATTERNS) + r")\s*$",
    re.IGNORECASE,
)
_TRAILING_SEP_RE = re.compile(r"[-_ ]+$")
_SEPARATOR_RE = re.compile(r"[-_ ]+")


def normalize_stem(filename: str) -> str:
    """Normalize a filename to a canonical stem for revision matching.

    Steps:
    1. Remove file extension
    2. Strip trailing format tags (-PDF, _PDF)
    3. Strip trailing revision patterns (_Revised, _v2, etc.)
    4. Lowercase, collapse separators, strip trailing separators
    """
    stem = Path(filename).stem

    # Iteratively strip format tags and revision patterns from the end
    # Loop because stripping one may reveal another (e.g., "Foo-PDF_(Revised)")
    changed = True
    while changed:
        changed = False
        new_stem = _FORMAT_TAG_RE.sub("", stem)
        if new_stem != stem:
            stem = _TRAILING_SEP_RE.sub("", new_stem)
            changed = True
        new_stem = _REVISION_PATTERN_RE.sub("", stem)
        if new_stem != stem:
            stem = _TRAILING_SEP_RE.sub("", new_stem)
            changed = True

    # Lowercase, collapse separators
    stem = stem.lower()
    stem = _SEPARATOR_RE.sub("_", stem)
    stem = stem.strip("_")

    return stem


def has_revision_indicator(filename: str) -> bool:
    """Check if a filename contains a trailing revision indicator."""
    stem = Path(filename).stem
    # Strip format tags first so "Foo-PDF_(Revised)" works
    stem = _FORMAT_TAG_RE.sub("", stem)
    return bool(_REVISION_DETECT_RE.search(stem))
