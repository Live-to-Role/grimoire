"""The Product model exposes the extraction-disposition columns."""
from grimoire.models.product import Product


def test_product_has_disposition_columns():
    cols = set(Product.__table__.columns.keys())
    assert "text_unextractable" in cols
    assert "extraction_error" in cols


def test_disposition_defaults_are_falsey():
    # Column default (DDL) is False; a fresh unmapped instance is None for both.
    p = Product(file_path="/t/x.pdf", file_name="x.pdf", file_size=1, file_hash="h")
    assert getattr(p, "text_unextractable", "missing") in (None, False)
    assert getattr(p, "extraction_error", "missing") in (None, "")
