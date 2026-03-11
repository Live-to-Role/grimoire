"""Tests for image extraction from PDFs."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_extract_images_creates_output_dir(tmp_path):
    """extract_images should create the output directory."""
    from grimoire.processors.image_extractor import extract_images

    # Create a minimal mock since we can't easily create a real PDF in tests
    output_dir = tmp_path / "images" / "1"
    assert not output_dir.exists()

    # We'll test with a mock PDF
    with patch("grimoire.processors.image_extractor.fitz") as mock_fitz:
        mock_doc = MagicMock()
        mock_doc.__len__ = lambda self: 0
        mock_doc.__iter__ = lambda self: iter([])
        mock_fitz.open.return_value = mock_doc

        result = extract_images(Path("/fake.pdf"), output_dir)

    assert output_dir.exists()
    assert result["image_count"] == 0
    assert (output_dir / "manifest.json").exists()


def test_extract_images_manifest_format(tmp_path):
    """Manifest should contain expected fields."""
    from grimoire.processors.image_extractor import extract_images

    output_dir = tmp_path / "images" / "1"

    with patch("grimoire.processors.image_extractor.fitz") as mock_fitz:
        mock_doc = MagicMock()
        mock_doc.__len__ = lambda self: 0
        mock_doc.__iter__ = lambda self: iter([])
        mock_fitz.open.return_value = mock_doc

        extract_images(Path("/fake.pdf"), output_dir)

    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert "images" in manifest
    assert "image_count" in manifest
    assert "total_pages" in manifest
    assert isinstance(manifest["images"], list)
