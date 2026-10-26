"""library_stats doubles as the health check."""
from grimoire.mcp import tools_meta
from tests.mcp.conftest import set_search_provider


async def test_library_stats_counts(db, library):
    out = await tools_meta.library_stats(db)

    assert out["products"] == 4  # duplicates excluded
    assert out["text_extracted"] == 3
    # Chunk embeddings exist for two products, but semantic search ranks over
    # product_search_vectors, and the fixture has none of those.
    assert out["embedded"] == 0
    assert out["confirmed_monsters"] == 1
    assert out["search_mode"] == "keyword_only"
    assert out["semantic_provider"] == "none"


async def test_library_stats_embedded_counts_search_vectors_of_live_products(db, library):
    from grimoire.models.product_search_vector import ProductSearchVector

    for key in ("sf1", "dupe"):
        sv = ProductSearchVector(
            product_id=library[key].id, embedding_model="test", embedding_dim=3
        )
        sv.set_vector([0.1, 0.2, 0.3])
        db.add(sv)
    await db.commit()

    out = await tools_meta.library_stats(db)
    assert out["embedded"] == 1  # the duplicate's vector does not count


async def test_library_stats_reports_hybrid_when_configured(db, library):
    await set_search_provider(db, "ollama")
    out = await tools_meta.library_stats(db)
    assert out["search_mode"] == "hybrid"
    assert out["semantic_provider"] == "ollama"
