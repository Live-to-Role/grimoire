"""Tests for extraction flow ordering and page counting."""

import pytest

from grimoire.processors import text_extractor
from grimoire.processors.text_extractor import (
    _get_page_count,
    extract_text_with_ocr_fallback,
)


def test_get_page_count(text_pdf):
    assert _get_page_count(text_pdf) == 1


def test_ocr_fallback_skips_ocr_for_text_pdf(text_pdf):
    result = extract_text_with_ocr_fallback(text_pdf)
    assert result["ocr_used"] is False
    assert "Grimoire Test Document" in result["markdown"]


def test_ocr_path_never_runs_standard_extraction(scanned_pdf, monkeypatch):
    """When detection says OCR, standard extraction must not run at all."""
    std_calls = []
    monkeypatch.setattr(
        text_extractor,
        "extract_text_to_markdown",
        lambda *a, **k: std_calls.append(1) or {"markdown": "", "total_pages": 1},
    )
    monkeypatch.setattr(
        text_extractor,
        "extract_with_ocr",
        lambda *a, **k: "## Page 1\n\nOCR TEXT\n\n",
    )
    monkeypatch.setattr(text_extractor, "TESSERACT_AVAILABLE", True)

    result = extract_text_with_ocr_fallback(scanned_pdf)

    assert result["ocr_used"] is True
    assert std_calls == []


def test_ocr_failure_falls_back_to_standard_extraction(scanned_pdf, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("tesseract exploded")

    monkeypatch.setattr(text_extractor, "extract_with_ocr", boom)
    monkeypatch.setattr(text_extractor, "TESSERACT_AVAILABLE", True)

    result = extract_text_with_ocr_fallback(scanned_pdf)

    assert result["ocr_used"] is False
    assert "OCR attempted but failed" in result["ocr_reason"]
    assert "markdown" in result  # standard extraction ran as fallback


def test_art_front_matter_book_skips_ocr(art_front_matter_pdf, monkeypatch):
    """A book with art front matter and a text body must never reach OCR."""
    ocr_calls = []
    monkeypatch.setattr(
        text_extractor,
        "extract_with_ocr",
        lambda *a, **k: ocr_calls.append(1) or "## Page 1\n\nOCR\n\n",
    )
    monkeypatch.setattr(text_extractor, "TESSERACT_AVAILABLE", True)

    result = extract_text_with_ocr_fallback(art_front_matter_pdf)

    assert ocr_calls == []
    assert result["ocr_used"] is False
    assert "adventurer descends" in result["markdown"]


def test_detect_needs_ocr_is_retired():
    assert not hasattr(text_extractor, "detect_needs_ocr")
