"""Tests for OCR extraction paths."""

import pytest

from grimoire.processors import text_extractor
from grimoire.processors.text_extractor import _find_tessdata


def test_find_tessdata_env_override(monkeypatch, tmp_path):
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "eng.traineddata").touch()
    monkeypatch.setenv("TESSDATA_PREFIX", str(tessdata))
    assert _find_tessdata() == str(tessdata)


def test_find_tessdata_rejects_dir_without_traineddata(monkeypatch, tmp_path):
    empty = tmp_path / "tessdata"
    empty.mkdir()
    monkeypatch.setenv("TESSDATA_PREFIX", str(empty))
    # Must not accept a dir that has no *.traineddata files
    result = _find_tessdata()
    assert result != str(empty)


@pytest.mark.skipif(
    _find_tessdata() is None, reason="tessdata language files not installed"
)
def test_pymupdf_ocr_reads_scanned_pdf(scanned_pdf):
    text = text_extractor.extract_with_pymupdf_ocr(scanned_pdf)
    assert "GRIMOIRE" in text.upper()


def test_extract_with_ocr_falls_back_when_pymupdf_ocr_fails(scanned_pdf, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no tessdata")

    monkeypatch.setattr(text_extractor, "extract_with_pymupdf_ocr", boom)
    monkeypatch.setattr(
        text_extractor, "_extract_with_pdf2image_ocr",
        lambda *a, **k: "## Page 1\n\nLEGACY OCR\n\n",
    )
    result = text_extractor.extract_with_ocr(scanned_pdf)
    assert "LEGACY OCR" in result
