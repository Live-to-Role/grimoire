"""Fixtures for the MCP tool tests.

A small library on disk: two products with page-anchored extracted text and
body chunks indexed for phrase lookup, one legacy product whose extraction
JSON has no page anchors, one product with no text at all, a tag, a
collection, and two bestiary entries (one confirmed, one pending).
"""
import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from grimoire.models import (
    Collection,
    CollectionProduct,
    MonsterEntry,
    Product,
    ProductEmbedding,
    ProductTag,
    Setting,
    Tag,
)
from grimoire.services.fts_service import index_product_chunks


def _write_extraction(tmp_path, name: str, pages: list[str] | None, flat: str | None = None):
    path = tmp_path / f"{name}.json"
    if pages is None:
        data = {"markdown": flat or "", "total_pages": 1, "method": "legacy"}
    else:
        data = {
            "markdown": "\n\n".join(pages),
            "pages": [{"page": i + 1, "markdown": text} for i, text in enumerate(pages)],
            "total_pages": len(pages),
            "method": "pymupdf4llm",
        }
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


async def _product(db, *, file_hash, title, text_path=None, chunks=(), **fields):
    product = Product(
        file_path=rf"D:\Games\{file_hash}.pdf",
        file_name=f"{file_hash}.pdf",
        file_size=1024,
        file_hash=file_hash,
        title=title,
        text_extracted=text_path is not None,
        extracted_text_path=text_path,
        **fields,
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
async def library(db, tmp_path):
    sf1_pages = [
        "# SF1 Volturnus\n\nThe party lands in a damaged shuttle.",
        "The Ul-Mor ride their lopers across the sand.",
        "The Kurabanda live in the treetops. Kurabanda scouts watch the party.",
    ]
    sf1 = await _product(
        db,
        file_hash="sf1",
        title="SF1 Volturnus, Planet of Mystery",
        text_path=_write_extraction(tmp_path, "sf1", sf1_pages),
        chunks=[(sf1_pages[0], 1), (sf1_pages[1], 2), (sf1_pages[2], 3)],
        game_system="Star Frontiers",
        product_type="adventure",
        publisher="TSR",
        page_count=3,
        level_range_min=1,
        level_range_max=3,
    )
    swamp_pages = [
        "# Marsh of Sorrows\n\nA swamp hex-crawl for levels 2 to 4.",
        "The ferryman demands a toll of memories.",
    ]
    swamp = await _product(
        db,
        file_hash="swamp",
        title="Marsh of Sorrows",
        text_path=_write_extraction(tmp_path, "swamp", swamp_pages),
        chunks=[(swamp_pages[0], 1), (swamp_pages[1], 2)],
        game_system="Dungeon Crawl Classics",
        product_type="adventure",
        publisher="Goodman Games",
        page_count=2,
        level_range_min=2,
        level_range_max=4,
    )
    legacy = await _product(
        db,
        file_hash="legacy",
        title="Old Flat Extraction",
        text_path=_write_extraction(tmp_path, "legacy", None, flat="flat text only"),
        game_system="Dungeon Crawl Classics",
        product_type="supplement",
    )
    bare = await _product(db, file_hash="bare", title="Never Extracted", product_type="map")
    dupe = await _product(db, file_hash="dupe", title="SF1 Volturnus (copy)", is_duplicate=True)

    tag = Tag(name="swamp", category="theme")
    db.add(tag)
    await db.flush()
    db.add(ProductTag(product_id=swamp.id, tag_id=tag.id))

    collection = Collection(name="Next campaign")
    db.add(collection)
    await db.flush()
    db.add(CollectionProduct(collection_id=collection.id, product_id=swamp.id))
    db.add(CollectionProduct(collection_id=collection.id, product_id=sf1.id))

    db.add(
        MonsterEntry(
            product_id=swamp.id,
            name="Bog Lurker",
            page_number=7,
            system_profile="dcc",
            raw_text="Bog Lurker: Init +1; Atk bite +3 melee (1d6) ...",
            ac=13,
            hd_dice="3d8",
            hd_value=3.0,
            hp_avg=13.5,
            attacks=json.dumps([{"name": "bite", "bonus": 3, "damage_dice": "1d6"}]),
            special_abilities=json.dumps(["drowning grip"]),
            environments=json.dumps(["swamp", "river"]),
            review_status="confirmed",
        )
    )
    db.add(
        MonsterEntry(
            product_id=swamp.id,
            name="Unreviewed Thing",
            page_number=9,
            system_profile="dcc",
            raw_text="...",
            hd_value=1.0,
            environments=json.dumps(["swamp"]),
            review_status="pending",
        )
    )
    await db.commit()
    return {
        "sf1": sf1,
        "swamp": swamp,
        "legacy": legacy,
        "bare": bare,
        "dupe": dupe,
        "tag": tag,
        "collection": collection,
    }


async def set_search_provider(db, provider: str) -> None:
    db.add(Setting(key="semantic_search_provider", value=json.dumps(provider)))
    await db.commit()


@pytest.fixture
async def mcp_sessions(engine):
    """Point the MCP tool wrappers at the test engine for in-process calls."""
    from grimoire.mcp import db as mcp_db

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    mcp_db.set_session_factory(factory)
    yield
    mcp_db.set_session_factory(None)
