"""The body index is a separate table from the metadata index.

products_fts is metadata-only and trigger-maintained. The body has a different
owner, a different lifecycle, and one row per chunk rather than one per
product, so it gets its own table.
"""
from sqlalchemy import text

from grimoire.database import _ensure_fts_table


async def _columns(db, table: str) -> list[str]:
    rows = (await db.execute(text(f"PRAGMA table_info({table})"))).all()
    return [r[1] for r in rows]


async def test_ensure_fts_table_creates_the_chunk_index(db):
    await _ensure_fts_table(await db.connection())

    assert await _columns(db, "product_chunks_fts") == [
        "chunk_text", "product_id", "chunk_index", "page_start", "page_end",
    ]


async def test_ensure_fts_table_is_idempotent(db):
    """It runs on every startup; a second call must not throw or wipe rows."""
    conn = await db.connection()
    await _ensure_fts_table(conn)
    await db.execute(text(
        "INSERT INTO product_chunks_fts(rowid, chunk_text, product_id, chunk_index,"
        " page_start, page_end) VALUES (1, 'kurabanda treetops', 7, 0, 32, 33)"
    ))

    await _ensure_fts_table(conn)

    rows = (await db.execute(text(
        "SELECT product_id FROM product_chunks_fts WHERE product_chunks_fts MATCH 'kurabanda'"
    ))).all()
    assert [r[0] for r in rows] == [7]
