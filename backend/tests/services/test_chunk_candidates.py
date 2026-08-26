"""Selecting candidate products from the body index."""
import pytest

from grimoire.models import Product, ProductEmbedding
from grimoire.services.fts_service import chunk_candidates, index_product_chunks


async def _make(db, *, title, file_hash, chunks, game_system=None, is_duplicate=False):
    product = Product(
        file_path=rf"D:\Games\{file_hash}.pdf",
        file_name=f"{file_hash}.pdf",
        file_size=1024,
        file_hash=file_hash,
        title=title,
        game_system=game_system,
        is_duplicate=is_duplicate,
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
    await index_product_chunks(db, product.id)
    await db.commit()
    return product


@pytest.fixture
async def library(db):
    sf1 = await _make(
        db, title="SF1 Volturnus", file_hash="sf1",
        chunks=[
            ("The party lands in a damaged shuttle.", 2),
            ("The Kurabanda live in the treetops. Kurabanda scouts watch.", 32),
        ],
        game_system="Star Frontiers",
    )
    other = await _make(
        db, title="Frontier Explorer", file_hash="fe",
        chunks=[("A single mention of Kurabanda in passing.", 5)],
        game_system="Star Frontiers",
    )
    dupe = await _make(
        db, title="SF1 Volturnus (copy)", file_hash="dupe",
        chunks=[("The Kurabanda live in the treetops.", 32)],
        is_duplicate=True,
    )
    return {"sf1": sf1, "other": other, "dupe": dupe}


async def test_finds_a_product_by_deep_body_text(db, library):
    hits = await chunk_candidates(db, "Kurabanda")

    assert library["sf1"].id in [pid for pid, _, _, _ in hits]


async def test_returns_the_page_of_the_matching_chunk(db, library):
    hits = await chunk_candidates(db, "Kurabanda")
    by_id = {pid: (snippet, page) for pid, _, snippet, page in hits}

    _, page = by_id[library["sf1"].id]
    assert page == 32


async def test_returns_one_row_per_product(db, library):
    """A product is scored by its single best chunk, matching TOP_K_CHUNKS=1."""
    hits = await chunk_candidates(db, "Kurabanda")
    ids = [pid for pid, _, _, _ in hits]

    assert len(ids) == len(set(ids))


async def test_snippet_contains_the_matched_term(db, library):
    hits = await chunk_candidates(db, "Kurabanda")
    by_id = {pid: snippet for pid, _, snippet, _ in hits}

    assert "Kurabanda" in by_id[library["sf1"].id]


async def test_duplicates_are_excluded(db, library):
    hits = await chunk_candidates(db, "Kurabanda")

    assert library["dupe"].id not in [pid for pid, _, _, _ in hits]


async def test_game_system_filter_applies(db, library):
    hits = await chunk_candidates(db, "Kurabanda", game_system="Traveller")

    assert hits == []


async def test_limit_is_respected(db, library):
    hits = await chunk_candidates(db, "Kurabanda", limit=1)

    assert len(hits) == 1
