"""handle_embed_task stores page anchors on chunk rows."""
import json

import pytest
from sqlalchemy import select

from grimoire.models import Product, ProductEmbedding
from grimoire.services import queue_processor
from grimoire.services.embeddings import EmbeddingResult


@pytest.fixture
def fake_embeddings(monkeypatch):
    async def _fake(texts, provider=None, model=None):
        # deterministic 8-dim unit-ish vectors
        return [
            EmbeddingResult(embedding=[float(i + 1)] * 8, model="fake-model")
            for i, _ in enumerate(texts)
        ]

    monkeypatch.setattr(queue_processor, "generate_embeddings", _fake, raising=False)
    import grimoire.services.embeddings as emb
    monkeypatch.setattr(emb, "generate_embeddings", _fake)
    return _fake


async def test_embed_task_stores_page_anchors(db, tmp_path, fake_embeddings):
    body = ("lorem ipsum " * 120).strip()  # ~1400 chars -> 2+ chunks
    text_file = tmp_path / "p.json"
    text_file.write_text(json.dumps({
        "markdown": f"## Page 1\n\n{body}\n\n## Page 2\n\n{body}\n",
        "pages": [
            {"page": 1, "markdown": f"## Page 1\n\n{body}\n\n"},
            {"page": 2, "markdown": f"## Page 2\n\n{body}\n"},
        ],
    }), encoding="utf-8")

    product = Product(
        file_path="/x/p.pdf", file_name="p.pdf", file_size=123_456,
        file_hash="embed-pages-1",
        title="Paged Book", text_extracted=True,
        extracted_text_path=str(text_file),
    )
    db.add(product)
    await db.commit()

    ok = await queue_processor.handle_embed_task(db, product)
    assert ok is True

    rows = (await db.execute(
        select(ProductEmbedding)
        .where(ProductEmbedding.product_id == product.id)
        .order_by(ProductEmbedding.chunk_index)
    )).scalars().all()
    assert len(rows) >= 3
    # chunk 0 is the metadata preamble -> NULL pages
    assert rows[0].page_start is None and rows[0].page_end is None
    # content chunks carry real page numbers
    content = rows[1:]
    assert all(r.page_start is not None for r in content)
    assert content[0].page_start == 1
    assert content[-1].page_end == 2


async def test_embed_task_legacy_flat_file_null_pages(db, tmp_path, fake_embeddings):
    text_file = tmp_path / "legacy.json"
    text_file.write_text(json.dumps({"markdown": "flat " * 400}), encoding="utf-8")

    product = Product(
        file_path="/x/l.pdf", file_name="l.pdf", file_size=123_456,
        file_hash="embed-pages-2",
        title="Legacy Book", text_extracted=True,
        extracted_text_path=str(text_file),
    )
    db.add(product)
    await db.commit()

    ok = await queue_processor.handle_embed_task(db, product)
    assert ok is True

    rows = (await db.execute(
        select(ProductEmbedding).where(ProductEmbedding.product_id == product.id)
    )).scalars().all()
    assert rows
    assert all(r.page_start is None and r.page_end is None for r in rows)
