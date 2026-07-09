"""Page-aware chunking: span mapping, page attribution, preamble handling."""
from grimoire.services.embeddings import (
    build_chunks_for_product,
    chunk_text,
    chunk_text_with_pages,
)


def _pages(sizes):
    """Build synthetic pages with known sizes; page text is 'pN ' repeated."""
    return [
        {"page": i + 1, "markdown": (f"p{i + 1} " * (size // 3)).strip()}
        for i, size in enumerate(sizes)
    ]


def test_chunk_text_default_is_1000():
    text = "word " * 1000  # 5000 chars
    chunks = chunk_text(text)
    assert all(len(c) <= 1100 for c in chunks)  # 1000 + boundary slack
    assert len(chunks) < 8  # ~5000/900 with overlap; 500-char chunks would give 11+


def test_single_page_chunks_carry_that_page():
    chunks = chunk_text_with_pages(_pages([2500]))
    assert len(chunks) >= 2
    assert all(ps == 1 and pe == 1 for _, ps, pe in chunks)


def test_cross_page_chunk_gets_a_range():
    # Two small pages: the chunk spanning both must report pages 1-2
    chunks = chunk_text_with_pages(_pages([600, 600]))
    spans = [(ps, pe) for _, ps, pe in chunks]
    assert (1, 2) in spans or ((1, 1) in spans and (2, 2) in spans and len(chunks) > 1)
    # At minimum: first chunk starts on page 1, last chunk ends on page 2
    assert chunks[0][1] == 1
    assert chunks[-1][2] == 2


def test_chunks_concatenate_to_full_content():
    pages = _pages([1500, 1500])
    chunks = chunk_text_with_pages(pages)
    # Every chunk's text appears in the joined page text
    joined = "\n\n".join(p["markdown"] for p in pages)
    for text, _, _ in chunks:
        assert text in joined


def test_build_chunks_preamble_has_null_pages():
    pages = _pages([1500])
    result = build_chunks_for_product("Title: X\nGame System: Y\n\n", pages, "")
    assert result[0][1] is None and result[0][2] is None  # preamble chunk
    assert "Title: X" in result[0][0]
    assert result[1][1] == 1  # first content chunk on page 1


def test_build_chunks_flat_fallback_when_no_pages():
    result = build_chunks_for_product("pre\n\n", None, "flat body " * 300)
    assert all(ps is None and pe is None for _, ps, pe in result)
    assert len(result) >= 2  # preamble + flat content chunks


def test_empty_preamble_skipped():
    result = build_chunks_for_product("", _pages([500]), "")
    assert result[0][1] == 1  # first chunk is content, not preamble


def test_chunk_text_short_input_is_stripped():
    # Short-circuit path (len <= chunk_size) must strip, matching the long
    # path's per-chunk .strip() — this is intentional, not a bug.
    assert chunk_text("  hello world  ") == ["hello world"]


def test_chunk_text_empty_and_whitespace_only_return_empty_list():
    # Deliberately NOT [""] or ["   "] — empty/whitespace-only input yields
    # no chunks at all under the short-circuit path.
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_text_with_pages_empty_list_is_safe():
    # Empty pages -> joined text is "" -> short-circuits to [] before the
    # page-mapping (page_at) ever runs.
    assert chunk_text_with_pages([]) == []
