"""search_library, find_phrase and search_pack."""
import pytest

from grimoire.mcp import tools_search
from grimoire.mcp.common import ToolError
from grimoire.services import search_service
from tests.mcp.conftest import _product, set_search_provider


@pytest.fixture
def fake_search(monkeypatch, library):
    """Stand in for the two-stage search: records the request, returns one hit."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from grimoire.api.routes.products import product_to_response
    from grimoire.models import Product, ProductTag

    calls = []

    async def fake(db, request):
        calls.append(request)
        # Loaded with tags, as search_service does, so the real serializer runs.
        product = (await db.execute(
            select(Product)
            .where(Product.id == library["swamp"].id)
            .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
        )).scalar_one()
        item = product_to_response(product).model_dump()
        item.update(
            score=0.91, match_type="both", matched_page=2,
            snippet="The ferryman demands a toll of memories.",
        )
        return {
            "query": request.query,
            "results": [item],
            "total_matches": 1,
            "interpretation": {"semantic_query": request.query, "source": "heuristic"},
        }

    monkeypatch.setattr(search_service, "search", fake)
    return calls


async def test_search_library_returns_compact_hits(db, library, fake_search):
    await set_search_provider(db, "ollama")

    out = await tools_search.search_library(db, query="swamp hex-crawl")

    assert out["mode"] == "hybrid"
    hit = out["results"][0]
    assert hit["product_id"] == library["swamp"].id
    assert hit["title"] == "Marsh of Sorrows"
    assert hit["matched_page"] == 2
    assert hit["match_type"] == "both"
    assert hit["score"] == 0.91
    assert hit["level_min"] == 2 and hit["level_max"] == 4
    # nothing bulky from ProductResponse leaks through
    assert "file_path" not in hit and "cover_url" not in hit
    assert out["interpretation"]["semantic_query"] == "swamp hex-crawl"


async def test_search_library_passes_filters_and_limit(db, library, fake_search):
    await set_search_provider(db, "ollama")

    await tools_search.search_library(
        db, query="x", limit=5, game_system="Dungeon Crawl Classics",
        product_type="adventure", level_min=2, level_max=3,
    )

    request = fake_search[0]
    assert request.top_k == 5
    assert request.game_system == "Dungeon Crawl Classics"
    assert request.product_type == "adventure"
    assert (request.level_min, request.level_max) == (2, 3)


async def test_search_library_clamps_limit(db, library, fake_search):
    await set_search_provider(db, "ollama")
    await tools_search.search_library(db, query="x", limit=500)
    assert fake_search[0].top_k == tools_search.MAX_RESULTS


async def test_search_library_without_provider_falls_back_to_keywords(db, library, fake_search):
    """The HTTP route rejects this case; the tool answers in keyword mode."""
    out = await tools_search.search_library(db, query="Kurabanda")

    assert fake_search == []
    assert out["mode"] == "keyword_only"
    assert "semantic" in out["note"].lower()
    assert [h["product_id"] for h in out["results"]] == [library["sf1"].id]
    assert out["results"][0]["match_type"] == "keyword"
    assert out["results"][0]["matched_page"] == 3


async def test_find_phrase_returns_page_and_clean_snippet(db, library):
    out = await tools_search.find_phrase(db, phrase="Kurabanda")

    assert out["results"][0]["product_id"] == library["sf1"].id
    assert out["results"][0]["title"] == "SF1 Volturnus, Planet of Mystery"
    assert out["results"][0]["page"] == 3
    assert "Kurabanda" in out["results"][0]["snippet"]
    assert "<mark>" not in out["results"][0]["snippet"]


async def test_find_phrase_filters_by_system(db, library):
    out = await tools_search.find_phrase(db, phrase="party", game_system="Star Frontiers")
    assert {h["product_id"] for h in out["results"]} == {library["sf1"].id}


async def test_find_phrase_empty_is_an_error(db, library):
    with pytest.raises(ToolError):
        await tools_search.find_phrase(db, phrase="   ")


async def test_search_pack_dedupes_and_keeps_best_score(db, library, monkeypatch):
    await set_search_provider(db, "ollama")
    scores = {"swamp": 0.4, "marsh": 0.9, "bog": 0.1}

    async def fake(db, query, **kw):
        pid = library["swamp"].id
        return {
            "mode": "hybrid",
            "results": [{"product_id": pid, "title": "Marsh of Sorrows", "score": scores[query]}],
        }

    monkeypatch.setattr(tools_search, "search_library", fake)

    out = await tools_search.search_pack(db, queries=["swamp", "marsh", "bog"])

    assert len(out["results"]) == 1
    hit = out["results"][0]
    assert hit["score"] == 0.9
    assert hit["matched_queries"] == ["swamp", "marsh", "bog"]
    assert hit["best_query"] == "marsh"
    assert out["mode"] == "hybrid"


async def test_search_pack_keeps_a_page_when_a_pageless_hit_scores_higher(db, library, monkeypatch):
    """A title match can outscore a body match for the same book. The score and
    best_query follow the winner, but the only page pointer must survive."""
    hits = {
        "swamp": {"score": 0.6, "matched_page": 32, "snippet": "the swamp ferryman"},
        "marsh": {"score": 0.8, "matched_page": None, "snippet": None},
    }

    async def fake(db, query, **kw):
        return {"mode": "hybrid", "results": [dict(product_id=7, title="Marsh", **hits[query])]}

    monkeypatch.setattr(tools_search, "search_library", fake)

    out = await tools_search.search_pack(db, queries=["swamp", "marsh"])

    hit = out["results"][0]
    assert hit["score"] == 0.8 and hit["best_query"] == "marsh"
    assert hit["matched_page"] == 32
    assert hit["snippet"] == "the swamp ferryman"


async def test_search_pack_global_limit_and_query_cap(db, library, monkeypatch):
    async def fake(db, query, **kw):
        return {"mode": "hybrid", "results": [
            {"product_id": i, "title": f"p{i}", "score": 1 / (i + 1)} for i in range(5)
        ]}

    monkeypatch.setattr(tools_search, "search_library", fake)

    out = await tools_search.search_pack(db, queries=["a", "b"], global_limit=2)
    assert [h["product_id"] for h in out["results"]] == [0, 1]

    with pytest.raises(ToolError):
        await tools_search.search_pack(db, queries=[f"q{i}" for i in range(11)])
    with pytest.raises(ToolError):
        await tools_search.search_pack(db, queries=[])


async def test_search_pack_does_not_interpret_each_phrasing(db, library, fake_search):
    """The caller already supplied the phrasings; one LLM interpretation per
    sub-query would be ten sequential round trips for nothing."""
    await set_search_provider(db, "ollama")

    await tools_search.search_library(db, query="swamp")
    assert fake_search[-1].interpret is True

    await tools_search.search_pack(db, queries=["swamp", "marsh", "bog"])
    assert len(fake_search) == 4
    assert all(request.interpret is False for request in fake_search[1:])


async def test_search_pack_keeps_the_keyword_note(db, library, fake_search):
    out = await tools_search.search_pack(db, queries=["Kurabanda", "Ul-Mor"])
    assert out["mode"] == "keyword_only"
    assert out["note"] == tools_search.KEYWORD_NOTE

    await set_search_provider(db, "ollama")
    out = await tools_search.search_pack(db, queries=["swamp"])
    assert out["mode"] == "hybrid"
    assert out.get("note") is None


async def test_keyword_level_filter_looks_past_the_first_page_of_hits(db, library):
    """Level filters are applied after the FTS LIMIT, so the tool must fetch
    deeper than `limit` or a filtered-out top hit leaves the answer empty."""
    from tests.mcp.conftest import _product

    high = await _product(
        db,
        file_hash="high",
        title="Crossing of the Damned",
        text_path=None,
        chunks=[("The ferryman waits by the long dark river under a cold moon.", 1)],
        level_range_min=5,
        level_range_max=7,
    )
    # The fixture's "Marsh of Sorrows" (levels 2-4) also says "ferryman" in a
    # shorter chunk, so it outranks `high` and alone fills limit=1.
    out = await tools_search.search_library(db, query="ferryman", limit=1, level_min=5)

    assert [h["product_id"] for h in out["results"]] == [high.id]


async def test_search_hides_superseded_revisions(db, library):
    """The Library hides superseded revisions everywhere; search must too, on
    the body path, the keyword path and the metadata candidates alike."""
    from grimoire.services.fts_service import fts_candidates
    from tests.mcp.conftest import _product

    old = await _product(
        db,
        file_hash="sf1-old",
        title="SF1 Volturnus, first printing",
        text_path=None,
        chunks=[("Kurabanda scouts watch the party from the trees.", 3)],
        is_superseded=True,
    )

    phrase = await tools_search.find_phrase(db, phrase="Kurabanda")
    assert [h["product_id"] for h in phrase["results"]] == [library["sf1"].id]

    keyword = await tools_search.search_library(db, query="Kurabanda")
    assert [h["product_id"] for h in keyword["results"]] == [library["sf1"].id]

    # Title match: the live SF1, not the superseded printing nor the duplicate.
    ids = {row[0] for row in await fts_candidates(db, "Volturnus")}
    assert ids == {library["sf1"].id}, (ids, old.id)


async def test_search_library_rejects_bad_levels_with_a_usable_message(db, library, fake_search):
    with pytest.raises(ToolError, match="level_min"):
        await tools_search.search_library(db, query="funnel", level_min=-1)
    with pytest.raises(ToolError, match="level_max"):
        await tools_search.search_library(db, query="funnel", level_max=-2)
    with pytest.raises(ToolError, match="level_min"):
        await tools_search.search_library(db, query="funnel", level_min=5, level_max=3)
    assert fake_search == []


async def test_search_library_type_filter_uses_the_stored_spelling(db, library, fake_search):
    # The tool docs used to suggest "rulebook"; the column holds core_rulebook.
    await _product(db, file_hash="core", title="Core Rules", product_type="core_rulebook")
    await set_search_provider(db, "ollama")

    await tools_search.search_library(db, query="x", product_type="Rulebook")

    assert fake_search[0].product_type == "core_rulebook"


async def test_keyword_search_type_filter_takes_any_known_spelling(db, library, fake_search):
    out = await tools_search.search_library(db, query="Kurabanda", product_type="Adventure")

    assert out["mode"] == "keyword_only"
    assert [h["product_id"] for h in out["results"]] == [library["sf1"].id]


async def test_find_phrase_type_filter_takes_any_known_spelling(db, library):
    out = await tools_search.find_phrase(db, phrase="Kurabanda", product_type="Adventure")

    assert [r["product_id"] for r in out["results"]] == [library["sf1"].id]
