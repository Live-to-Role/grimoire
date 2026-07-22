"""Tests for the /re-embed-mismatched repair endpoint.

The endpoint has to catch two distinct ways a product can end up unsearchable
after an embedding-model switch, not just the obvious one.
"""

from sqlalchemy import select

from grimoire.api.routes.semantic import re_embed_mismatched
from grimoire.models import ProcessingQueue, Product, ProductEmbedding
from grimoire.models.product_search_vector import ProductSearchVector

TARGET = "nomic-embed-text"


async def seed_product(db, path, *, chunk_model, sv_model=None, text_extracted=True):
    """Create a product with chunk embeddings and optionally a search vector."""
    product = Product(
        file_path=path, file_name=path.rsplit("/", 1)[-1],
        file_size=1, file_hash=path, title=path,
        text_extracted=text_extracted, extracted_text_path=f"{path}.json",
    )
    db.add(product)
    await db.flush()

    embedding = ProductEmbedding(
        product_id=product.id, chunk_index=0, chunk_text="chunk",
        embedding_model=chunk_model, embedding_dim=384 if "MiniLM" in chunk_model else 768,
    )
    embedding.set_embedding_vector([0.1] * embedding.embedding_dim)
    db.add(embedding)

    if sv_model:
        dim = 384 if "MiniLM" in sv_model else 768
        sv = ProductSearchVector(
            product_id=product.id, embedding_model=sv_model, embedding_dim=dim,
        )
        sv.set_vector([0.1] * dim)
        db.add(sv)

    await db.flush()
    return product


async def queued_ids(db):
    result = await db.execute(
        select(ProcessingQueue.product_id).where(
            ProcessingQueue.task_type == "embed",
            ProcessingQueue.status == "pending",
        )
    )
    return set(result.scalars().all())


async def test_queues_product_with_stale_chunks_and_no_search_vector(db):
    """The cohort the old query missed entirely.

    A product embedded by the previous model never got a search vector written
    (the averaged vector is only stored on a successful embed), so a query that
    looks only at ProductSearchVector rows cannot see it.
    """
    product = await seed_product(db, "/t/stale-no-sv.pdf", chunk_model="all-MiniLM-L6-v2")

    await re_embed_mismatched(db=db, target_model=TARGET)

    assert product.id in await queued_ids(db)


async def test_queues_product_with_mismatched_search_vector(db):
    product = await seed_product(
        db, "/t/stale-sv.pdf", chunk_model="all-MiniLM-L6-v2", sv_model="all-MiniLM-L6-v2",
    )

    await re_embed_mismatched(db=db, target_model=TARGET)

    assert product.id in await queued_ids(db)


async def test_skips_product_already_on_target_model(db):
    product = await seed_product(
        db, "/t/current.pdf", chunk_model=TARGET, sv_model=TARGET,
    )

    await re_embed_mismatched(db=db, target_model=TARGET)

    assert product.id not in await queued_ids(db)


async def test_skips_product_without_extracted_text(db):
    """The embed handler raises on these, so queuing them only manufactures failures."""
    product = await seed_product(
        db, "/t/no-text.pdf", chunk_model="all-MiniLM-L6-v2", text_extracted=False,
    )

    await re_embed_mismatched(db=db, target_model=TARGET)

    assert product.id not in await queued_ids(db)


async def test_does_not_double_queue_on_rerun(db):
    product = await seed_product(db, "/t/rerun.pdf", chunk_model="all-MiniLM-L6-v2")

    await re_embed_mismatched(db=db, target_model=TARGET)
    second = await re_embed_mismatched(db=db, target_model=TARGET)

    result = await db.execute(
        select(ProcessingQueue.id).where(
            ProcessingQueue.product_id == product.id,
            ProcessingQueue.task_type == "embed",
        )
    )
    assert len(result.scalars().all()) == 1
    assert second["queued"] == 0


async def test_preserves_old_vectors_until_each_product_is_re_embedded(db):
    """Queuing must not bulk-delete: the handler replaces per product, so a
    pre-emptive delete would blank out search for everything still in the queue.
    """
    product = await seed_product(
        db, "/t/keep.pdf", chunk_model="all-MiniLM-L6-v2", sv_model="all-MiniLM-L6-v2",
    )

    await re_embed_mismatched(db=db, target_model=TARGET)

    still_there = await db.execute(
        select(ProductEmbedding.id).where(ProductEmbedding.product_id == product.id)
    )
    assert still_there.scalars().all()
