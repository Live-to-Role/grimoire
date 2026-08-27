"""Re-embedding a product must leave the body index consistent.

handle_embed_task deletes every chunk and rewrites it. If the index is not
cleared first, the old rows survive as orphans and stale text stays findable
forever.
"""
import json

import pytest
from sqlalchemy import delete, text

from grimoire.database import _ensure_fts_table
from grimoire.models import Product, ProductEmbedding
from grimoire.services.fts_service import clear_product_chunk_index, index_product_chunks


@pytest.fixture
async def product_with_index(db, tmp_path):
    await _ensure_fts_table(await db.connection())
    text_file = tmp_path / "extracted.json"
    text_file.write_text(json.dumps({"markdown": "placeholder"}), encoding="utf-8")

    product = Product(
        file_path=r"D:\Games\sf1.pdf",
        file_name="sf1.pdf",
        file_size=1024,
        file_hash="sf1hash",
        title="SF1 Volturnus",
        text_extracted=True,
        extracted_text_path=str(text_file),
    )
    db.add(product)
    await db.flush()

    emb = ProductEmbedding(
        product_id=product.id,
        chunk_index=0,
        chunk_text="The Kurabanda live in the treetops.",
        embedding_model="test",
        embedding_dim=3,
        page_start=32,
        page_end=33,
    )
    emb.set_embedding_vector([0.1, 0.2, 0.3])
    db.add(emb)
    await db.commit()
    await index_product_chunks(db, product.id)
    await db.commit()
    return product


async def _terms_findable(db, term: str) -> int:
    rows = (await db.execute(text(
        "SELECT rowid FROM product_chunks_fts WHERE product_chunks_fts MATCH :q"
    ), {"q": term})).all()
    return len(rows)


async def test_clearing_before_replacement_leaves_no_orphan(db, product_with_index):
    """The ordering that matters: clear while the embedding rows still exist."""
    assert await _terms_findable(db, "Kurabanda") == 1

    await clear_product_chunk_index(db, product_with_index.id)
    await db.execute(
        delete(ProductEmbedding).where(
            ProductEmbedding.product_id == product_with_index.id
        )
    )
    await db.commit()

    assert await _terms_findable(db, "Kurabanda") == 0


async def test_clearing_after_replacement_strands_the_old_row(db, product_with_index):
    """Documents the hazard the ordering above exists to avoid.

    If the embeddings are deleted first, clear_product_chunk_index has nothing
    left to resolve rowids from, and the stale text stays findable.
    """
    await db.execute(
        delete(ProductEmbedding).where(
            ProductEmbedding.product_id == product_with_index.id
        )
    )
    await db.commit()
    await clear_product_chunk_index(db, product_with_index.id)
    await db.commit()

    assert await _terms_findable(db, "Kurabanda") == 1


async def test_embed_handler_reindexes_the_body(db, product_with_index, monkeypatch):
    """Re-embedding replaces the indexed text rather than stacking on it."""
    from grimoire.services import embeddings as embeddings_module
    from grimoire.services import queue_processor

    async def fake_generate(chunks, *args, **kwargs):
        return [
            embeddings_module.EmbeddingResult(embedding=[0.1, 0.2, 0.3], model="test")
            for _ in chunks
        ]

    monkeypatch.setattr(embeddings_module, "generate_embeddings", fake_generate)
    monkeypatch.setattr(
        embeddings_module,
        "build_chunks_for_product",
        lambda preamble, pages, flat_text: [("The Sathar fleet withdraws.", 40, 41)],
    )

    await queue_processor.handle_embed_task(db, product_with_index)

    assert await _terms_findable(db, "Kurabanda") == 0
    assert await _terms_findable(db, "Sathar") == 1
