"""Tests for cover extraction render scaling."""

import pytest
from PIL import Image

from grimoire.services.processor import _cover_scale, extract_cover_image


def test_cover_scale_letter_page_renders_near_target():
    # 612x792pt letter page, 300px target -> scale ~0.61, far below old 2.0
    scale = _cover_scale(612, 792, 300)
    expected = min(300 / 612, 400 / 792) * 1.25
    assert scale == pytest.approx(expected)
    assert scale < 1.0


def test_cover_scale_tiny_page_capped_at_two():
    # A tiny page must not be upscaled past the old 2.0 behavior
    assert _cover_scale(100, 100, 300) == 2.0


def test_cover_scale_degenerate_page_returns_safe_default():
    assert _cover_scale(0, 0, 300) == 1.0


def test_extract_cover_image_output_fits_target_box(text_pdf, tmp_path):
    out = tmp_path / "cover.jpg"
    assert extract_cover_image(text_pdf, out, size=300) is True
    with Image.open(out) as img:
        assert img.width <= 300
        assert img.height <= 400
