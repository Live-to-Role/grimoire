"""The "search content" toggle must actually search document text.

`search_fts` backs `/search?search_content=true` (Library.tsx's toggle). It
used to match against products_fts.extracted_text — the first 50,000
characters of the document. That column is gone: the body now lives in
product_chunks_fts, uncapped and carrying page numbers.

Without this, the toggle silently returns metadata matches with no snippets,
which is not an error the user can see.
"""
import pytest

from grimoire.models import Product, ProductEmbedding
from grimoire.services.fts_service import index_product_chunks, search_fts


async def _make(db, *, title, file_hash, chunks=(), publisher=None):
    product = Product(
        file_path=rf"D:\Games\{file_hash}.pdf",
        file_name=f"{file_hash}.pdf",
        file_size=1024,
        file_hash=file_hash,
        title=title,
        publisher=publisher,
        text_extracted=True,
    )
    db.add(product)
    await db.flush()
    for i, (body, page) in enumerate(chunks):
        emb = ProductEmbedding(
            product_id=product.id,
            chunk_index=i,
            chunk_text=body,
            embedding_model="test",
            embedding_dim=3,
            page_start=page,
            page_end=page,
        )
        emb.set_embedding_vector([0.1, 0.2, 0.3])
        db.add(emb)
    await db.commit()
    if chunks:
        await index_product_chunks(db, product.id)
        await db.commit()
    return product


@pytest.fixture
async def library(db):
    deep = await _make(
        db, title="SF1 Volturnus Planet of Mystery", file_hash="sf1",
        chunks=[
            ("The party lands in a damaged shuttle.", 2),
            ("The Kurabanda live in the treetops of Volturnus.", 32),
        ],
    )
    titled = await _make(
        db, title="Kurabanda Field Guide", file_hash="guide",
        chunks=[("An unrelated body paragraph about shuttles.", 1)],
    )
    return {"deep": deep, "titled": titled}


async def test_finds_a_term_that_appears_only_in_the_body(db, library):
    """The whole point of the toggle."""
    results = await search_fts(db, "Kurabanda")

    assert library["deep"].id in [r["id"] for r in results]


async def test_body_match_carries_a_snippet_and_page(db, library):
    results = await search_fts(db, "Kurabanda")
    hit = next(r for r in results if r["id"] == library["deep"].id)

    assert "Kurabanda" in hit["snippet"]
    assert hit["matched_page"] == 32


async def test_metadata_matches_still_work(db, library):
    """Title hits must not be lost now that the body is a second source."""
    results = await search_fts(db, "Kurabanda")

    assert library["titled"].id in [r["id"] for r in results]


async def test_a_product_is_returned_once(db, library):
    """Matching in both title and body must not duplicate the row."""
    results = await search_fts(db, "Kurabanda")
    ids = [r["id"] for r in results]

    assert len(ids) == len(set(ids))


async def test_limit_is_respected(db, library):
    results = await search_fts(db, "Kurabanda", limit=1)

    assert len(results) == 1


async def test_no_match_returns_nothing(db, library):
    assert await search_fts(db, "Sathar") == []
