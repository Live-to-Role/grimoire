"""FTS MATCH builder + lean candidate query.

The builder drops stopwords and single characters because under prefix
matching they explode: "a"* alone matched most of the index and turned a
0.02s query into 1.3s, and the snippet()+hydration the old path added on top
pushed a single hybrid-search FTS call into seconds.
"""
from grimoire.services.fts_service import build_fts_match


def test_stopwords_and_single_chars_dropped():
    m = build_fts_match("a descent into hell aboard a train")
    assert '"a"*' not in m
    assert '"descent"*' in m and '"hell"*' in m and '"train"*' in m
    # "into" and "aboard" carry signal and are kept
    assert '"into"*' in m and '"aboard"*' in m


def test_content_terms_prefix_matched_and_ored():
    assert build_fts_match("hunting a dragon") == '"hunting"* OR "dragon"*'


def test_all_stopwords_falls_back_to_raw_terms():
    # Never return an empty MATCH for a non-empty query; degrade instead.
    m = build_fts_match("a the of")
    assert m is not None
    assert "MATCH" not in (m or "")  # it's a term expression, not a keyword
    assert '"a"*' in m  # fell back to raw terms


def test_empty_query_returns_none():
    assert build_fts_match("   ") is None


def test_embedded_quotes_are_stripped():
    m = build_fts_match('dragon" OR products_fts')
    # No unescaped quote can break out of the quoted term / inject syntax.
    assert '""' not in m
    assert m.count('"') % 2 == 0
