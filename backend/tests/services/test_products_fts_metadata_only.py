"""products_fts holds metadata and nothing else.

Sharing one table between the metadata trigger and the body writer is what
produced dc377a7. The body now lives in product_chunks_fts, so the shared
ownership goes away rather than being managed.
"""
from sqlalchemy import text

from grimoire.database import _ensure_fts_table


async def _columns(db) -> list[str]:
    rows = (await db.execute(text("PRAGMA table_info(products_fts)"))).all()
    return [r[1] for r in rows]


async def test_products_fts_has_no_body_column(db):
    await _ensure_fts_table(await db.connection())

    assert await _columns(db) == [
        "title", "file_name", "publisher", "game_system",
        "product_type", "description",
    ]


async def test_existing_seven_column_table_is_migrated(db):
    """Databases in the wild carry the old seven-column table."""
    conn = await db.connection()
    await db.execute(text("DROP TABLE IF EXISTS products_fts"))
    await db.execute(text("""
        CREATE VIRTUAL TABLE products_fts USING fts5(
            title, file_name, publisher, game_system, product_type,
            description, extracted_text
        )
    """))

    await _ensure_fts_table(conn)

    assert "extracted_text" not in await _columns(db)
