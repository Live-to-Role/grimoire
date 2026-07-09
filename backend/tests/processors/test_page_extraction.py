"""Page-anchored extraction: per-page markdown from pymupdf4llm + marker splitting."""
from pathlib import Path

import pytest

from grimoire.processors.text_extractor import (
    PYMUPDF4LLM_AVAILABLE,
    extract_text_to_markdown,
    extract_with_pymupdf4llm_pages,
    split_pages_by_markers,
)


@pytest.fixture
def three_page_pdf(tmp_path) -> Path:
    """Create a 3-page PDF with distinct text per page."""
    import fitz

    path = tmp_path / "three.pdf"
    doc = fitz.open()
    for i, word in enumerate(["alpha", "bravo", "charlie"], start=1):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i} content: {word} " * 3)
    doc.save(str(path))
    doc.close()
    return path


@pytest.mark.skipif(not PYMUPDF4LLM_AVAILABLE, reason="pymupdf4llm not installed")
def test_pymupdf4llm_pages_returns_one_entry_per_page(three_page_pdf):
    pages = extract_with_pymupdf4llm_pages(three_page_pdf)
    assert [p["page"] for p in pages] == [1, 2, 3]
    assert "alpha" in pages[0]["markdown"]
    assert "charlie" in pages[2]["markdown"]


@pytest.mark.skipif(not PYMUPDF4LLM_AVAILABLE, reason="pymupdf4llm not installed")
def test_pymupdf4llm_pages_respects_page_range(three_page_pdf):
    pages = extract_with_pymupdf4llm_pages(three_page_pdf, start_page=2, end_page=3)
    assert [p["page"] for p in pages] == [2, 3]
    assert "bravo" in pages[0]["markdown"]


def test_split_pages_by_markers_basic():
    md = "## Page 1\n\nfirst page text\n\n---\n\n## Page 2\n\nsecond page text\n"
    pages = split_pages_by_markers(md)
    assert [p["page"] for p in pages] == [1, 2]
    assert "first page text" in pages[0]["markdown"]
    assert "second page text" in pages[1]["markdown"]
    # Joining the segments reproduces the original text exactly
    assert "".join(p["markdown"] for p in pages) == md


def test_split_pages_by_markers_preamble_attaches_to_first_page():
    md = "Some front matter\n\n## Page 1\n\nbody\n\n## Page 2\n\nmore\n"
    pages = split_pages_by_markers(md)
    assert pages[0]["page"] == 1
    assert "Some front matter" in pages[0]["markdown"]


def test_split_pages_by_markers_returns_none_without_markers():
    assert split_pages_by_markers("just a flat blob of text") is None


@pytest.mark.skipif(not PYMUPDF4LLM_AVAILABLE, reason="pymupdf4llm not installed")
def test_extract_text_to_markdown_includes_pages(three_page_pdf):
    result = extract_text_to_markdown(three_page_pdf)
    assert "error" not in result
    assert result["method"] == "pymupdf4llm"
    assert [p["page"] for p in result["pages"]] == [1, 2, 3]
    # markdown key still present and is the joined page text
    assert result["markdown"] == "\n\n".join(p["markdown"] for p in result["pages"])
