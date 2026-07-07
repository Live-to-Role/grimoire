"""Tests for gallery image extraction."""

import fitz
import pytest

from grimoire.processors.image_extractor import _render_scale, extract_images


def test_extract_images_dedupes_repeated_image(repeated_image_pdf, tmp_path):
    out_dir = tmp_path / "gallery"
    manifest = extract_images(repeated_image_pdf, out_dir)
    # Same image on 3 pages must be saved exactly once
    assert manifest["image_count"] == 1
    assert manifest["total_pages"] == 3
    saved = [p for p in out_dir.iterdir() if p.name != "manifest.json"]
    assert len(saved) == 1


def test_render_scale_normal_page_keeps_2x():
    # Letter page at 2x is 1224x1584 — under the cap, unchanged
    assert _render_scale(612, 792) == 2.0


def test_render_scale_caps_huge_pages():
    # A 3000pt-wide map page must be capped to ~2048px output
    scale = _render_scale(3000, 2000)
    assert scale == pytest.approx(2048 / 3000)
    assert scale < 1.0
