# backend/tests/test_monster_segmenter.py
"""Tests for heuristic monster candidate segmentation."""

from grimoire.processors.monster_segmenter import Candidate, segment_pages
from grimoire.processors.system_profiles import get_profile

DCC_PAGE = """
## Orc

Fierce warriors of the wastes, orcs raid caravans by night.

Orc: Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; MV 30'; Act 1d20;
SV Fort +1, Ref +0, Will -1; AL C.

## Giant Rat

Giant Rat: Init +2; Atk bite +1 melee (1d3); AC 13; HD 1d6; MV 30'; Act 1d20;
SV Fort +2, Ref +2, Will -1; AL N.
"""

OSR_PAGE = """
**PERYTON**

A monstrous winged stag with the shadow of a man. Found in lonely mountains.

AC 7 [12], HD 4, Att 1 x antlers (2d4), THAC0 15, MV 240' (80') flying,
SV D10 W11 P12 B13 S14, ML 9, AL Chaotic, XP 125

The peryton must consume the heart of its victim.
"""

PROSE_PAGE = """
The judge should feel free to add wandering monsters. Consult chapter 4
for guidance on encounter design and terrain.
"""


def test_dcc_segmentation_finds_both_monsters():
    pages = [{"page": 12, "markdown": DCC_PAGE}]
    candidates = segment_pages(pages, get_profile("dcc"))
    names = [c.name_guess for c in candidates]
    assert names == ["Orc", "Giant Rat"]
    assert all(c.page == 12 for c in candidates)
    assert "AC 13" in candidates[0].raw_text
    assert "Giant Rat" not in candidates[0].raw_text


def test_osr_segmentation_finds_peryton_with_prose():
    pages = [{"page": 142, "markdown": OSR_PAGE}]
    candidates = segment_pages(pages, get_profile("osr"))
    assert len(candidates) == 1
    assert candidates[0].name_guess == "PERYTON"
    assert candidates[0].page == 142
    assert "THAC0 15" in candidates[0].raw_text
    assert "consume the heart" in candidates[0].raw_text


def test_prose_page_yields_nothing():
    pages = [{"page": 3, "markdown": PROSE_PAGE}]
    assert segment_pages(pages, get_profile("dcc")) == []
    assert segment_pages(pages, get_profile("osr")) == []


def test_anchor_without_header_still_emits_candidate():
    pages = [{"page": 7, "markdown": "Init +0; Atk bite +2 melee (1d4); AC 12; HD 2d8; MV 20'; Act 1d20; SV Fort +1, Ref +1, Will +0; AL N."}]
    candidates = segment_pages(pages, get_profile("dcc"))
    assert len(candidates) == 1
    assert candidates[0].name_guess  # non-empty fallback


TIGHTLY_PACKED_PAGE = """## Orc
Orc: Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; MV 30'; Act 1d20; SV Fort +1, Ref +0, Will -1; AL C.
Rat: Init +2; Atk bite +1 melee (1d3); AC 12; HD 1d6; MV 30'; Act 1d20; SV Fort +2, Ref +2, Will -1; AL N."""


def test_tightly_packed_anchors_do_not_drop_earlier_candidate():
    # Regression: when a later anchor's header lookback lands on or before an
    # earlier candidate's start, the earlier block's slice could be clipped to
    # empty and silently dropped. High recall is load-bearing here (see module
    # docstring) -- missing a real monster is far more costly than a junk
    # candidate, so both entries must be emitted even when packed this tight.
    pages = [{"page": 5, "markdown": TIGHTLY_PACKED_PAGE}]
    candidates = segment_pages(pages, get_profile("dcc"))
    assert len(candidates) == 2
    # A non-empty rescue isn't enough: the rescued first candidate must also
    # carry its own anchor's statline, not just the header it was rescued
    # back to. A name-only candidate ("## Orc" with no stats) is invisible to
    # the downstream LLM normalizer -- it will be rejected as not-a-monster,
    # so the monster is still effectively lost even though the slice is
    # "non-empty".
    assert "AC 13" in candidates[0].raw_text
    assert "HD 1d8+1" in candidates[0].raw_text
