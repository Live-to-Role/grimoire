"""Classify image-heavy PDFs as Map, Stock Art, Token, etc."""

import re


# Patterns checked against filename AND full path (case-insensitive)
_CLASSIFICATION_RULES = [
    ("Map", [r"map", r"cartograph", r"battlemap", r"battle\s*map", r"dungeon\s*map", r"floorplan", r"floor\s*plan"]),
    ("Token", [r"\btoken", r"\btokens\b"]),
    ("Portrait", [r"portrait"]),
    ("Handout", [r"handout"]),
    ("Scene", [r"\bscene\b"]),
    ("Texture", [r"texture"]),
    ("Stock Art", [r"stock\s*art", r"\bart\s*pack", r"illustration", r"clip\s*art"]),
]


def classify_image_content(filename: str, file_path: str) -> str:
    """
    Classify an image-heavy PDF based on filename and path heuristics.

    Args:
        filename: The PDF filename
        file_path: Full path to the PDF

    Returns:
        Classification string: "Map", "Stock Art", "Token", etc.
        Defaults to "Stock Art" if no pattern matches.
    """
    search_text = f"{filename} {file_path}".lower()

    for label, patterns in _CLASSIFICATION_RULES:
        for pattern in patterns:
            if re.search(pattern, search_text, re.IGNORECASE):
                return label

    return "Stock Art"
