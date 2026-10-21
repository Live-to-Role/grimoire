"""library_stats doubles as the health check."""
from grimoire.mcp import tools_meta
from tests.mcp.conftest import set_search_provider


async def test_library_stats_counts(db, library):
    out = await tools_meta.library_stats(db)

    assert out["products"] == 4  # duplicates excluded
    assert out["text_extracted"] == 3
    assert out["embedded"] == 2
    assert out["confirmed_monsters"] == 1
    assert out["search_mode"] == "keyword_only"
    assert out["semantic_provider"] == "none"


async def test_library_stats_reports_hybrid_when_configured(db, library):
    await set_search_provider(db, "ollama")
    out = await tools_meta.library_stats(db)
    assert out["search_mode"] == "hybrid"
    assert out["semantic_provider"] == "ollama"
