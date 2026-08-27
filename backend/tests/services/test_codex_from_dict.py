"""`CodexProduct.from_dict` against the reshaped `/identify` payload.

Codex's `/identify` returns `ProductDetailSerializer`, which dropped `author`,
`genre`, `publication_year`, `dtrpg_url` and `game_system_slug`, and turned
`publisher` and `game_system` into nested objects. `from_dict` still read all
of them as flat values, so `publisher` came back as a `dict` and
`sync_product_from_codex` bound it to a `String(255)` column.

Shapes here are taken from `tests/fixtures/codex/identify_by_title.json`,
captured from the live API on 2026-08-24.

Both encodings have to parse: the plan calls the flat form defensive rather
than load-bearing (the deployment is current), but an older deployment should
not start writing dicts into the database either.
"""
import json
import pathlib

import pytest

from grimoire.services.codex import CodexProduct

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "codex"


def _product(**overrides):
    """A minimal /identify product payload in the current (nested) shape."""
    base = {
        "id": "4d3d631e-4a9e-4fdc-8cc8-2b8b46a2d0cc",
        "title": "0A The Tomb of Rakoss the Undying",
        "publisher": {"id": "682b6678", "name": "Fire Born Games", "slug": "fire-born-games"},
        "game_system": None,
        "game_systems": [],
        "credits": [],
        "links": [],
        "publication_date": None,
        "dtrpg_id": "",
    }
    base.update(overrides)
    return base


# --- publisher -------------------------------------------------------------

def test_nested_publisher_becomes_its_name():
    product = CodexProduct.from_dict(_product())
    assert product.publisher == "Fire Born Games"


def test_flat_publisher_still_works():
    """An older deployment sends a string; it must not regress."""
    product = CodexProduct.from_dict(_product(publisher="Goodman Games"))
    assert product.publisher == "Goodman Games"


def test_missing_publisher_is_none():
    assert CodexProduct.from_dict(_product(publisher=None)).publisher is None


# --- game system -----------------------------------------------------------

def test_nested_game_system_becomes_its_name():
    product = CodexProduct.from_dict(_product(
        game_system={"name": "Dungeon Crawl Classics", "slug": "dcc"},
    ))
    assert product.game_system == "Dungeon Crawl Classics"
    assert product.game_system_slug == "dcc"


def test_a_single_unnominated_system_is_used():
    """`game_system` is null until a primary link is nominated (Codex's own
    comment). With exactly one candidate there is nothing to disambiguate."""
    product = CodexProduct.from_dict(_product(
        game_system=None,
        game_systems=[{"name": "OSRIC", "slug": "osric", "is_primary": False}],
    ))
    assert product.game_system == "OSRIC"


def test_several_unnominated_systems_stay_unset():
    """The captured fixture: two systems, neither primary. Picking one is a guess."""
    product = CodexProduct.from_dict(_product(
        game_system=None,
        game_systems=[
            {"name": "Classic D&D/AD&D", "slug": "classic-d-d-ad-d", "is_primary": False},
            {"name": "OSRIC", "slug": "osric", "is_primary": False},
        ],
    ))
    assert product.game_system is None


def test_a_nominated_primary_wins_over_the_others():
    product = CodexProduct.from_dict(_product(
        game_system=None,
        game_systems=[
            {"name": "Classic D&D/AD&D", "slug": "c", "is_primary": False},
            {"name": "OSRIC", "slug": "osric", "is_primary": True},
        ],
    ))
    assert product.game_system == "OSRIC"


# --- publication year ------------------------------------------------------

def test_publication_year_is_derived_from_publication_date():
    product = CodexProduct.from_dict(_product(publication_date="2021-06-15"))
    assert product.publication_year == 2021


def test_an_explicit_publication_year_is_preferred():
    """Older deployments still send the year outright."""
    product = CodexProduct.from_dict(_product(publication_year=1998))
    assert product.publication_year == 1998


def test_an_unparseable_publication_date_is_ignored():
    product = CodexProduct.from_dict(_product(publication_date="not-a-date"))
    assert product.publication_year is None


# --- marketplace -----------------------------------------------------------

def test_dtrpg_id_is_read():
    assert CodexProduct.from_dict(_product(dtrpg_id="119267")).dtrpg_id == "119267"


def test_dtrpg_url_is_derived_from_links():
    """The column is gone from Codex; the link list carries it now."""
    product = CodexProduct.from_dict(_product(links=[
        {"url": "https://itch.io/x", "label": "itch.io"},
        {"url": "https://www.drivethrurpg.com/product/119267/f1", "label": "DriveThruRPG"},
    ]))
    assert product.dtrpg_url == "https://www.drivethrurpg.com/product/119267/f1"
    assert len(product.links) == 2


def test_a_flat_dtrpg_url_still_works():
    product = CodexProduct.from_dict(_product(dtrpg_url="https://example.com/p"))
    assert product.dtrpg_url == "https://example.com/p"


# --- credits ---------------------------------------------------------------

def _credit(name, role="author"):
    return {"author": {"name": name}, "role": role}


def test_author_comes_from_author_credits():
    product = CodexProduct.from_dict(_product(credits=[
        _credit("Trevor Stamper"),
        _credit("Brian Gilkison", "co_author"),
    ]))
    assert product.author == "Trevor Stamper, Brian Gilkison"


def test_non_author_credits_are_not_treated_as_authors():
    """A cartographer in the author field is worse than a blank one."""
    product = CodexProduct.from_dict(_product(credits=[
        _credit("Someone Else", "cartographer"),
        _credit("A Third", "editor"),
    ]))
    assert product.author is None


def test_a_flat_author_still_works():
    assert CodexProduct.from_dict(_product(author="Matt Robertson")).author == "Matt Robertson"


# --- the real payload ------------------------------------------------------

def test_the_captured_payload_yields_only_scalars():
    """The regression that started this: no dict may reach a scalar column."""
    payload = json.loads((FIXTURES / "identify_by_title.json").read_text(encoding="utf-8"))
    product = CodexProduct.from_dict(payload["product"])

    for field in ("title", "publisher", "author", "game_system", "genre",
                  "product_type", "publication_year", "page_count",
                  "estimated_runtime", "description", "dtrpg_url"):
        value = getattr(product, field)
        assert value is None or isinstance(value, (str, int, float)), (
            f"{field} is {type(value).__name__}, which cannot bind to a scalar column"
        )

    assert product.publisher == "Fire Born Games"
    assert product.dtrpg_id == "119267"
