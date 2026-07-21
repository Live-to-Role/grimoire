"""Deleting a product must remove its child rows, not orphan-nullify them.

Regression test for the duplicates bulk-delete 500: the Product-side
collections created by ProductEmbedding/ContributionQueue backrefs used
SQLAlchemy's default cascade, which nullifies the child FK on parent delete.
Both child FK columns are NOT NULL, so the flush raised IntegrityError.
"""

import pytest
from sqlalchemy import func, select

from grimoire.models import Product
from grimoire.models.contribution import ContributionQueue
from grimoire.models.embedding import ProductEmbedding
from grimoire.models.monster_entry import MonsterEntry
from grimoire.models.product_search_vector import ProductSearchVector
from grimoire.models.queue import ProcessingQueue
from grimoire.services.duplicate_service import bulk_delete_duplicates


async def _make_product(db, file_hash: str, is_duplicate: bool) -> Product:
    product = Product(
        file_path=f"/tmp/{file_hash}-{is_duplicate}.pdf",
        file_name=f"{file_hash}.pdf",
        file_hash=file_hash,
        file_size=1024,
        is_duplicate=is_duplicate,
        is_missing=False,
    )
    db.add(product)
    await db.flush()
    return product


async def test_bulk_delete_duplicate_with_embeddings(db):
    """A duplicate that has embeddings deletes cleanly and takes them with it."""
    canonical = await _make_product(db, "cascadehash", is_duplicate=False)
    duplicate = await _make_product(db, "cascadehash", is_duplicate=True)
    duplicate.duplicate_of_id = canonical.id

    db.add(
        ProductEmbedding(
            product_id=duplicate.id,
            chunk_index=0,
            chunk_text="hello",
            embedding=b"\x00\x00\x00\x00",
            embedding_model="test",
            embedding_dim=1,
        )
    )
    db.add(
        ContributionQueue(
            product_id=duplicate.id,
            contribution_data="{}",
        )
    )
    await db.flush()

    result = await bulk_delete_duplicates(db, [duplicate.id], delete_files=False)

    assert result["success"] is True
    assert result["deleted_records"] == 1
    assert result["errors"] == []

    remaining = await db.execute(select(Product.id).where(Product.id == duplicate.id))
    assert remaining.scalar_one_or_none() is None

    orphan_embeddings = await db.execute(
        select(func.count(ProductEmbedding.id)).where(
            ProductEmbedding.product_id == duplicate.id
        )
    )
    assert orphan_embeddings.scalar() == 0

    orphan_contributions = await db.execute(
        select(func.count(ContributionQueue.id)).where(
            ContributionQueue.product_id == duplicate.id
        )
    )
    assert orphan_contributions.scalar() == 0

    # Canonical is untouched
    kept = await db.execute(select(Product.id).where(Product.id == canonical.id))
    assert kept.scalar_one_or_none() == canonical.id


async def test_delete_leaves_no_orphans_in_any_child_table(db):
    """Deleting a product cleans up every table holding a FK to products.id.

    SQLite FK enforcement is off, so ondelete="CASCADE" is inert and each of
    these needs an ORM-level delete-orphan cascade to avoid orphan rows.
    """
    canonical = await _make_product(db, "orphanhash", is_duplicate=False)
    duplicate = await _make_product(db, "orphanhash", is_duplicate=True)
    duplicate.duplicate_of_id = canonical.id

    db.add(ProcessingQueue(product_id=duplicate.id, task_type="text_extraction"))
    db.add(
        ProductSearchVector(
            product_id=duplicate.id,
            vector=b"\x00\x00\x00\x00",
            embedding_model="test",
            embedding_dim=1,
        )
    )
    db.add(
        MonsterEntry(
            product_id=duplicate.id,
            name="Goblin",
            system_profile="osr",
            raw_text="a goblin",
        )
    )
    db.add(
        ProductEmbedding(
            product_id=duplicate.id,
            chunk_index=0,
            chunk_text="hello",
            embedding=b"\x00\x00\x00\x00",
            embedding_model="test",
            embedding_dim=1,
        )
    )
    db.add(ContributionQueue(product_id=duplicate.id, contribution_data="{}"))
    await db.flush()

    dup_id = duplicate.id
    result = await bulk_delete_duplicates(db, [dup_id], delete_files=False)
    assert result["success"] is True
    assert result["deleted_records"] == 1

    for model in (
        ProcessingQueue,
        ProductSearchVector,
        MonsterEntry,
        ProductEmbedding,
        ContributionQueue,
    ):
        count = await db.execute(
            select(func.count()).select_from(model).where(model.product_id == dup_id)
        )
        assert count.scalar() == 0, f"{model.__tablename__} left orphan rows"
