"""get_product, list_products, get_page and get_text."""
import pytest

from grimoire.mcp import tools_products
from grimoire.mcp.common import ToolError


async def test_get_product_metadata_tags_collections(db, library):
    out = await tools_products.get_product(db, product_id=library["swamp"].id)

    assert out["title"] == "Marsh of Sorrows"
    assert out["game_system"] == "Dungeon Crawl Classics"
    assert out["publisher"] == "Goodman Games"
    assert out["level_min"] == 2 and out["level_max"] == 4
    assert out["page_count"] == 2
    assert out["tags"] == ["swamp"]
    assert out["collections"] == [{"id": library["collection"].id, "name": "Next campaign"}]
    assert out["text_extracted"] is True
    assert out["has_page_anchors"] is True
    assert "file_path" not in out


async def test_get_product_reports_legacy_and_bare_extraction(db, library):
    legacy = await tools_products.get_product(db, product_id=library["legacy"].id)
    assert legacy["text_extracted"] is True and legacy["has_page_anchors"] is False

    bare = await tools_products.get_product(db, product_id=library["bare"].id)
    assert bare["text_extracted"] is False and bare["has_page_anchors"] is False


async def test_get_product_unknown_id(db, library):
    with pytest.raises(ToolError, match="999999"):
        await tools_products.get_product(db, product_id=999999)


async def test_list_products_hides_duplicates_and_paginates(db, library):
    out = await tools_products.list_products(db)

    titles = [p["title"] for p in out["results"]]
    assert "SF1 Volturnus (copy)" not in titles
    assert out["total"] == 4
    assert titles == sorted(titles)

    page = await tools_products.list_products(db, limit=2, offset=2)
    assert len(page["results"]) == 2
    assert page["offset"] == 2 and page["total"] == 4


async def test_list_products_filters(db, library):
    by_name = await tools_products.list_products(db, query="volturnus")
    assert [p["product_id"] for p in by_name["results"]] == [library["sf1"].id]

    by_system = await tools_products.list_products(db, game_system="Dungeon Crawl Classics")
    assert {p["product_id"] for p in by_system["results"]} == {
        library["swamp"].id, library["legacy"].id
    }

    by_tag = await tools_products.list_products(db, tag="Swamp")
    assert [p["product_id"] for p in by_tag["results"]] == [library["swamp"].id]

    by_collection = await tools_products.list_products(
        db, collection_id=library["collection"].id
    )
    assert {p["product_id"] for p in by_collection["results"]} == {
        library["swamp"].id, library["sf1"].id
    }

    by_type = await tools_products.list_products(db, product_type="map")
    assert [p["product_id"] for p in by_type["results"]] == [library["bare"].id]


async def test_get_page_returns_one_page(db, library):
    out = await tools_products.get_page(db, product_id=library["sf1"].id, page=3)

    assert out["title"] == "SF1 Volturnus, Planet of Mystery"
    assert out["page_count"] == 3
    assert [p["page"] for p in out["pages"]] == [3]
    assert "Kurabanda" in out["pages"][0]["markdown"]
    assert out["truncated"] is False


async def test_get_page_with_context_clips_to_document(db, library):
    out = await tools_products.get_page(db, product_id=library["sf1"].id, page=1, context_pages=5)
    assert [p["page"] for p in out["pages"]] == [1, 2, 3]


async def test_get_page_out_of_range(db, library):
    with pytest.raises(ToolError, match="3 pages"):
        await tools_products.get_page(db, product_id=library["sf1"].id, page=4)
    with pytest.raises(ToolError):
        await tools_products.get_page(db, product_id=library["sf1"].id, page=0)


async def test_get_page_errors_name_the_fix(db, library):
    with pytest.raises(ToolError, match="text extraction"):
        await tools_products.get_page(db, product_id=library["bare"].id, page=1)
    with pytest.raises(ToolError, match="re-extract"):
        await tools_products.get_page(db, product_id=library["legacy"].id, page=1)


async def test_get_page_caps_total_characters(db, library, monkeypatch):
    monkeypatch.setattr(tools_products, "MAX_CHARS", 60)
    out = await tools_products.get_page(db, product_id=library["sf1"].id, page=1, context_pages=2)

    total = sum(len(p["markdown"]) for p in out["pages"])
    assert total <= 60
    assert out["truncated"] is True


async def test_get_text_windows_the_markdown(db, library):
    first = await tools_products.get_text(db, product_id=library["swamp"].id, max_chars=20)
    assert len(first["text"]) == 20
    assert first["offset"] == 0
    assert first["next_offset"] == 20
    assert first["total_chars"] > 20

    rest = await tools_products.get_text(
        db, product_id=library["swamp"].id, offset=20, max_chars=100000
    )
    assert rest["next_offset"] is None
    assert len(first["text"] + rest["text"]) == first["total_chars"]
    assert len(rest["text"]) <= tools_products.MAX_CHARS


async def test_get_text_works_for_legacy_flat_files(db, library):
    out = await tools_products.get_text(db, product_id=library["legacy"].id)
    assert out["text"] == "flat text only"


async def test_get_text_without_extraction(db, library):
    with pytest.raises(ToolError, match="text extraction"):
        await tools_products.get_text(db, product_id=library["bare"].id)


async def _gapped_product(db, tmp_path):
    """A pdfplumber-style extraction: markers only for pages with text, so page 3 is absent."""
    import json

    from tests.mcp.conftest import _product

    pages = [(1, "# Gaps\n\nIntro."), (2, "Second page."), (4, "The fourth page, after a blank one.")]
    path = tmp_path / "gaps.json"
    path.write_text(json.dumps({
        "markdown": "\n\n".join(t for _, t in pages),
        "pages": [{"page": n, "markdown": t} for n, t in pages],
        "total_pages": 4,
        "method": "pdfplumber",
    }), encoding="utf-8")
    return await _product(db, file_hash="gaps", title="Gaps", text_path=str(path), page_count=4)


async def test_get_page_reads_a_page_after_a_gap(db, library, tmp_path):
    product = await _gapped_product(db, tmp_path)

    out = await tools_products.get_page(db, product_id=product.id, page=4)

    assert out["page_count"] == 4
    assert [p["page"] for p in out["pages"]] == [4]
    assert "fourth" in out["pages"][0]["markdown"]


async def test_get_page_on_a_missing_page_is_an_error_not_an_empty_list(db, library, tmp_path):
    product = await _gapped_product(db, tmp_path)

    with pytest.raises(ToolError, match="no extracted text"):
        await tools_products.get_page(db, product_id=product.id, page=3)
    with pytest.raises(ToolError, match="out of range"):
        await tools_products.get_page(db, product_id=product.id, page=5)


async def test_get_page_context_skips_missing_pages(db, library, tmp_path):
    product = await _gapped_product(db, tmp_path)
    out = await tools_products.get_page(db, product_id=product.id, page=4, context_pages=2)
    assert [p["page"] for p in out["pages"]] == [2, 4]


async def test_disk_reads_run_off_the_event_loop(db, library, monkeypatch):
    """Extraction JSON can be tens of MB; parsing it inline stalls every request."""
    import threading

    from grimoire.services import processor

    threads = []
    real_pages, real_text = processor.get_extracted_pages, processor.get_extracted_text

    def pages(product):
        threads.append(threading.current_thread())
        return real_pages(product)

    def text(product):
        threads.append(threading.current_thread())
        return real_text(product)

    monkeypatch.setattr(processor, "get_extracted_pages", pages)
    monkeypatch.setattr(processor, "get_extracted_text", text)

    await tools_products.get_page(db, product_id=library["sf1"].id, page=1)
    await tools_products.get_text(db, product_id=library["sf1"].id)
    await tools_products.get_product(db, product_id=library["sf1"].id)

    assert len(threads) >= 3
    assert all(t is not threading.main_thread() for t in threads)
