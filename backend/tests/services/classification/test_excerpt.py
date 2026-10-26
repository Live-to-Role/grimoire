import re

from grimoire.models import CodexProduct
from grimoire.services.classification.excerpt import (
    build_description_excerpt,
    build_excerpt,
    estimate_tokens,
)

HEADER = {"filename": "book.pdf", "codex_title": "Book"}
FILLER = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "


def _filler(n_chars: int) -> str:
    return (FILLER * (n_chars // len(FILLER) + 1))[:n_chars]


def _pages(n: int, size: int = 600, inserts: dict[int, str] | None = None) -> dict:
    inserts = inserts or {}
    pages = []
    for i in range(1, n + 1):
        text = _filler(size)
        if i in inserts:
            mid = size // 2
            text = text[:mid] + " " + inserts[i] + " " + text[mid:]
        pages.append({"page": i, "markdown": text})
    return {"pages": pages, "markdown": "\n".join(p["markdown"] for p in pages)}


def _head_pages(text: str) -> list[int]:
    head = text.split("# Passages mentioning levels")[0]
    return [int(n) for n in re.findall(r"--- page (\d+) ---", head)]


def _window_tags(text: str) -> list[str]:
    if "# Passages mentioning levels" not in text:
        return []
    tail = text.split("# Passages mentioning levels")[1]
    return re.findall(r"--- (page|offset) (\d+) ---", tail)


def test_estimate_tokens():
    assert estimate_tokens("x" * 400) == 100


def test_header_is_rendered_as_key_value_lines():
    ex = build_excerpt(_pages(2), HEADER)
    assert ex.text.startswith("# Document\nfilename: book.pdf\ncodex_title: Book\n")
    assert ex.source == "pdf"


def test_head_stops_at_budget_and_tags_pages():
    ex = build_excerpt(_pages(20), HEADER)
    pages = _head_pages(ex.text)
    assert pages[:3] == [1, 2, 3]
    assert 15 <= len(pages) <= 17
    assert ex.windows == 0 and ex.unpaged is False


def test_level_windows_merge_and_order():
    two_hits = "for characters of levels 3-5, " + _filler(50) + " best for 4th-level parties"
    ex = build_excerpt(_pages(60, inserts={40: two_hits, 50: "a 1st-level adventure"}), HEADER)
    assert _window_tags(ex.text) == [("page", "40"), ("page", "50")]
    assert ex.windows == 2
    assert ex.text.index("# Passages mentioning levels") > ex.text.index("# Opening pages")


def test_windows_capped_at_max_earliest_first():
    inserts = {p: "for 2nd-level characters" for p in range(30, 40)}
    ex = build_excerpt(_pages(60, inserts=inserts), HEADER)
    assert [int(n) for _, n in _window_tags(ex.text)] == [30, 31, 32, 33, 34, 35]


def test_hit_inside_the_head_is_not_repeated_as_a_window():
    ex = build_excerpt(_pages(30, inserts={2: "for levels 1-3"}), HEADER)
    assert "levels 1-3" in ex.text and ex.windows == 0


def test_hard_cap_trims_head_before_windows():
    ex = build_excerpt(
        _pages(100, inserts={90: "an adventure for levels 5-7"}), HEADER, head_tokens=6000
    )
    assert ex.tokens <= 4000 and estimate_tokens(ex.text) <= 4000
    assert _window_tags(ex.text) == [("page", "90")]
    assert "levels 5-7" in ex.text


def test_dcc_zero_level_matches():
    ex = build_excerpt(_pages(40, inserts={30: "a 0-level funnel for 12–16 characters"}), HEADER)
    assert ex.windows == 1 and "0-level funnel" in ex.text


def test_page_number_and_spell_level_do_not_match():
    noise = "see page 12. You regain 3rd-level spell slots. A level 5 wizard casts it."
    ex = build_excerpt(_pages(40, inserts={30: noise}), HEADER)
    assert ex.windows == 0


def test_spell_levels_do_not_spend_the_windows():
    inserts = {p: "cast as a 2nd-level spell" for p in range(25, 31)}
    inserts[35] = "for 3rd-level characters"
    ex = build_excerpt(_pages(60, inserts=inserts), HEADER)
    assert _window_tags(ex.text) == [("page", "35")]


def test_unpaged_fallback_flags_and_uses_offsets():
    body = _filler(30000) + " for levels 2-4 " + _filler(2000)
    ex = build_excerpt({"markdown": body}, HEADER)
    assert ex.unpaged is True
    tags = _window_tags(ex.text)
    assert len(tags) == 1 and tags[0][0] == "offset" and int(tags[0][1]) > 29000
    assert ex.tokens <= 4000


def test_description_excerpt_source():
    cp = CodexProduct(
        id="x", slug="s", title="Sea Dogs", publisher="Pub", page_count=12,
        description="A pirate adventure for 3rd-level characters.",
    )
    ex = build_description_excerpt(cp)
    assert ex.source == "description" and ex.unpaged is False
    assert "title: Sea Dogs" in ex.text and "publisher: Pub" in ex.text
    assert "page_count: 12" in ex.text and "3rd-level characters" in ex.text


def test_5e_spell_blocks_and_class_features_do_not_spend_the_windows():
    # The common 5e formats name no "spell": a school after the level, and class
    # features that say when a character gains them.
    noise = [
        "### Shield\n*1st-level abjuration*\n**Casting Time:** 1 reaction",
        "### Fireball\n*3rd-level evocation*\n**Range:** 150 feet",
        "### Mage Hand\n*Conjuration cantrip*",
        "When you reach 3rd level, you choose an archetype.",
        "Starting at 6th level, you can attack twice.",
        "### Hold Person\n*2nd-level enchantment*",
    ]
    inserts = {25 + i: text for i, text in enumerate(noise)}
    inserts[40] = "An adventure for four 5th-level characters."
    ex = build_excerpt(_pages(60, inserts=inserts), HEADER)
    assert _window_tags(ex.text) == [("page", "40")]
