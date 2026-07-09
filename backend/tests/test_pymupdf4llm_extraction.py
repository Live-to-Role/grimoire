"""Tests for the pymupdf4llm extraction backend."""

import pytest

from grimoire.processors.text_extractor import (
    PYMUPDF4LLM_AVAILABLE,
    extract_text_to_markdown,
    extract_with_pymupdf4llm,
    get_available_extractors,
)

pytestmark = pytest.mark.skipif(
    not PYMUPDF4LLM_AVAILABLE, reason="pymupdf4llm not installed"
)


def test_pymupdf4llm_extracts_content(text_pdf):
    md = extract_with_pymupdf4llm(text_pdf)
    assert "Grimoire Test Document" in md


def test_pymupdf4llm_respects_page_range(text_pdf):
    md = extract_with_pymupdf4llm(text_pdf, start_page=1, end_page=1)
    assert "Grimoire Test Document" in md


def test_extract_text_to_markdown_prefers_pymupdf4llm(text_pdf):
    result = extract_text_to_markdown(text_pdf)
    assert result["method"] == "pymupdf4llm"
    assert "Grimoire Test Document" in result["markdown"]
    assert result["total_pages"] == 1


def test_empty_output_falls_through_to_next_backend(text_pdf, monkeypatch):
    from grimoire.processors import text_extractor

    monkeypatch.setattr(
        text_extractor,
        "extract_with_pymupdf4llm_pages",
        lambda *a, **k: [{"page": 1, "markdown": "   \n  "}],
    )
    result = text_extractor.extract_text_to_markdown(text_pdf)
    assert result["method"] != "pymupdf4llm"
    assert "Grimoire Test Document" in result["markdown"]


def test_available_extractors_reports_pymupdf4llm():
    assert "pymupdf4llm" in get_available_extractors()
