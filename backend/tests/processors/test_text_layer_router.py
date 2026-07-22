"""Whole-document text-layer coverage routing (replaces first-3-pages sampling)."""

from grimoire.processors.text_extractor import (
    TEXT_LAYER_COVERAGE_THRESHOLD,
    TEXT_LAYER_MIN_CHARS,
    assess_text_layer,
)


def test_defaults_match_spec():
    assert TEXT_LAYER_MIN_CHARS == 100
    assert TEXT_LAYER_COVERAGE_THRESHOLD == 0.10


def test_art_front_matter_book_uses_text_layer(art_front_matter_pdf):
    """The regression that started this work: art cover + art title page must not
    condemn a 394-page text-layer book to OCR."""
    result = assess_text_layer(art_front_matter_pdf)
    assert result["total_pages"] == 10
    assert result["pages_with_text"] == 7
    assert result["coverage"] == 0.7
    assert result["needs_ocr"] is False


def test_image_only_book_needs_ocr(repeated_image_pdf):
    result = assess_text_layer(repeated_image_pdf)
    assert result["total_pages"] == 3
    assert result["pages_with_text"] == 0
    assert result["coverage"] == 0.0
    assert result["has_images"] is True
    assert result["needs_ocr"] is True


def test_no_images_never_routes_to_ocr(text_pdf):
    """A sparse page with no images has nothing for OCR to read."""
    result = assess_text_layer(text_pdf)
    assert result["has_images"] is False
    assert result["needs_ocr"] is False


def test_coverage_threshold_boundary(art_front_matter_pdf):
    """coverage == threshold is NOT below it, so it stays on the text-layer path."""
    below = assess_text_layer(art_front_matter_pdf, coverage_threshold=0.8)
    at = assess_text_layer(art_front_matter_pdf, coverage_threshold=0.7)
    assert below["needs_ocr"] is True
    assert at["needs_ocr"] is False


def test_min_chars_boundary(art_front_matter_pdf):
    """Lowering min_chars lets the 5-char front-matter credit lines count."""
    result = assess_text_layer(art_front_matter_pdf, min_chars=1)
    assert result["pages_with_text"] == 10


def test_missing_file_does_not_claim_ocr(tmp_path):
    result = assess_text_layer(tmp_path / "nope.pdf")
    assert result["needs_ocr"] is False
    assert result["total_pages"] == 0
    assert "not found" in result["reason"].lower()
