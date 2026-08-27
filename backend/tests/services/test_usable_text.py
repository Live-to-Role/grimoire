"""Un-flagging must not re-OCR a book that already has its text.

Verification against the real library found the guard blocking 1,711 products,
of which only 156 have no text at all. The other 1,555 already carry extracted
text — `City State of the Invincible Overlord` has 499,032 characters — so
treating every un-flag as "this is a scan" would set `is_scanned` falsely and
queue 1,555 needless OCR passes.

`text_extracted` alone is too blunt to decide: measured across the blocked
population it is True for products whose text layer holds **zero characters**
(`The Lost Treasure of Correa`, 15pg, 0 chars; `Simple 5E Horror`, 28pg, 0
chars). Those do need OCR.

The floor is per *page*, not absolute — 800 characters is plenty for a
two-page handout and nothing at all for a 200-page book. Measured on the
book-typed blocked population: p5 = 83 chars/page, p10 = 126, p25 = 388,
p50 = 1,162. 100 sits in the sparse gap between the text-less tail and real
books, and sends 7% of them to OCR.
"""
import json

import pytest

from grimoire.models import Product
from grimoire.services.processor import MIN_USABLE_CHARS_PER_PAGE, has_usable_text


def _product(tmp_path, char_count=None, page_count=10, text_extracted=True):
    path = None
    if char_count is not None:
        path = tmp_path / "text.json"
        path.write_text(json.dumps({"char_count": char_count}), encoding="utf-8")
    return Product(
        file_path=r"D:\Games\thing.pdf", file_name="thing.pdf", file_size=1,
        file_hash="h", title="A Thing",
        page_count=page_count,
        text_extracted=text_extracted,
        extracted_text_path=str(path) if path else None,
    )


def test_a_real_book_has_usable_text(tmp_path):
    """City State of the Invincible Overlord: 499k chars over 216 pages."""
    assert has_usable_text(_product(tmp_path, char_count=499_032, page_count=216)) is True


def test_an_empty_text_layer_does_not_count(tmp_path):
    """`Simple 5E Horror` — text_extracted is True, the layer holds nothing."""
    assert has_usable_text(_product(tmp_path, char_count=0, page_count=28)) is False


def test_a_sparse_layer_does_not_count(tmp_path):
    """1,243 chars over 45 pages is 28/page — a broken extraction, not a book."""
    assert has_usable_text(_product(tmp_path, char_count=1_243, page_count=45)) is False


def test_a_short_document_is_judged_per_page(tmp_path):
    """800 chars is plenty for two pages and nothing for two hundred."""
    assert has_usable_text(_product(tmp_path, char_count=800, page_count=2)) is True
    assert has_usable_text(_product(tmp_path, char_count=800, page_count=200)) is False


def test_never_extracted_has_no_usable_text(tmp_path):
    assert has_usable_text(_product(tmp_path, char_count=None, text_extracted=False)) is False


def test_a_missing_extraction_file_has_no_usable_text(tmp_path):
    product = _product(tmp_path, char_count=5000)
    product.extracted_text_path = str(tmp_path / "gone.json")
    assert has_usable_text(product) is False


def test_an_unknown_page_count_errs_toward_ocr(tmp_path):
    """Can't compute per-page, so assume the worse case. A wasted OCR pass is
    cheap and flags itself via text_unextractable; skipping a needed one leaves
    the book unsearchable, which is the bug being fixed."""
    assert has_usable_text(_product(tmp_path, char_count=50_000, page_count=None)) is False


def test_the_floor_is_the_measured_one():
    assert MIN_USABLE_CHARS_PER_PAGE == 100
