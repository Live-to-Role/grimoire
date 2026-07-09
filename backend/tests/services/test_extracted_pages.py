"""get_extracted_pages accessor + OCR handler page persistence."""
import json

from grimoire.services.processor import get_extracted_pages, get_extracted_text


class FakeProduct:
    def __init__(self, path):
        self.text_extracted = True
        self.extracted_text_path = str(path)


def _write(tmp_path, data):
    f = tmp_path / "1.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


def test_pages_returned_when_present(tmp_path):
    f = _write(tmp_path, {
        "markdown": "## Page 1\n\nhello\n",
        "pages": [{"page": 1, "markdown": "## Page 1\n\nhello\n"}],
    })
    pages = get_extracted_pages(FakeProduct(f))
    assert pages == [{"page": 1, "markdown": "## Page 1\n\nhello\n"}]


def test_pages_none_for_legacy_flat_file(tmp_path):
    f = _write(tmp_path, {"markdown": "flat text only"})
    assert get_extracted_pages(FakeProduct(f)) is None
    # legacy reads still work
    assert get_extracted_text(FakeProduct(f)) == "flat text only"


def test_pages_none_when_file_missing(tmp_path):
    p = FakeProduct(tmp_path / "nope.json")
    assert get_extracted_pages(p) is None


def test_pages_none_when_not_extracted(tmp_path):
    p = FakeProduct(tmp_path / "1.json")
    p.text_extracted = False
    assert get_extracted_pages(p) is None
