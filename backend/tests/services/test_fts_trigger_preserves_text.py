"""The FTS update trigger must not destroy the indexed body text.

`update_search_vector` writes `products_fts.extracted_text`, but the
`products_fts_update` trigger rewrites the whole row on every UPDATE of
`products` using a 6-column INSERT into a 7-column table. That leaves
`extracted_text` NULL, so OCR'd books are searchable by title only.

The indexer trips this itself: it sets `product.deep_indexed = True` and
commits *after* writing the row, wiping the body it just wrote.
"""

import json

import pytest
from sqlalchemy import text

from grimoire.database import _ensure_fts_table
from grimoire.models import Product
from grimoire.services.fts_service import update_search_vector


async def _fts_body(db, product_id: int) -> str:
    row = (await db.execute(
        text("SELECT extracted_text FROM products_fts WHERE rowid = :i"),
        {"i": product_id},
    )).first()
    return (row[0] or "") if row else ""


async def _matches(db, term: str) -> list[int]:
    rows = (await db.execute(
        text("SELECT rowid FROM products_fts WHERE products_fts MATCH :q"),
        {"q": term},
    )).all()
    return [r[0] for r in rows]


@pytest.fixture
async def fts_db(db):
    """The `db` fixture only runs create_all, which skips the FTS table."""
    await _ensure_fts_table(await db.connection())
    return db


@pytest.fixture
async def indexed_product(fts_db, tmp_path):
    text_file = tmp_path / "extracted.json"
    text_file.write_text(
        json.dumps({"markdown": "The Kurabanda live in the treetops. " * 50}),
        encoding="utf-8",
    )
    product = Product(
        title="SF1 Volturnus Planet of Mystery",
        file_name="sf1.pdf",
        file_path="/library/sf1.pdf",
        file_size=1024,
        file_hash="sf1hash",
        text_extracted=True,
        extracted_text_path=str(text_file),
    )
    fts_db.add(product)
    await fts_db.commit()
    return product


async def test_update_search_vector_indexes_the_body(fts_db, indexed_product):
    """Baseline: the body reaches the index and is searchable."""
    assert await update_search_vector(fts_db, indexed_product) is True

    assert "Kurabanda" in await _fts_body(fts_db, indexed_product.id)
    assert indexed_product.id in await _matches(fts_db, "Kurabanda")


async def test_body_survives_a_later_product_update(fts_db, indexed_product):
    """Any later UPDATE of the product must not blank the indexed body.

    `ai_identify` writing a publisher is enough to make a book unsearchable.
    """
    await update_search_vector(fts_db, indexed_product)
    assert indexed_product.id in await _matches(fts_db, "Kurabanda")

    indexed_product.publisher = "TSR"
    await fts_db.commit()

    assert "Kurabanda" in await _fts_body(fts_db, indexed_product.id)
    assert indexed_product.id in await _matches(fts_db, "Kurabanda")


async def test_metadata_edits_still_reach_the_index(fts_db, indexed_product):
    """The trigger must keep doing its actual job: refreshing metadata."""
    await update_search_vector(fts_db, indexed_product)

    indexed_product.publisher = "TSR"
    await fts_db.commit()

    assert indexed_product.id in await _matches(fts_db, "TSR")
