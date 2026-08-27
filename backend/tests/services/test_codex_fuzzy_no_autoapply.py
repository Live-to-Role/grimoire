"""A fuzzy Codex match must never overwrite local metadata.

Phase 0 caught this against the live API: local "Zombie Reign" by Angry Engine
Games matched Codex's "SoRoPlay GamTools Zine: Zombie Ref" by Ken Wickham at
`fuzzy` / 0.818, and `sync_product_from_codex` was about to rename the local
product to it.

Nothing gated it. `identify_by_title` accepts any `exact` *or* `fuzzy` match
(`codex.py:315`) despite a docstring promising a confidence threshold, and
`sync_product_from_codex` wrote `match.confidence` onto the product without
ever reading it back.

Codex's catalogue carries almost no `file_hashes`, so the title fallback is the
normal path rather than the exceptional one — this decides what happens to
essentially every product a sync touches. Decision (2026-08-24): **only an
exact match auto-applies.** A fuzzy match is a suggestion and writes nothing.
"""
import pytest

from grimoire.services import sync_service
from grimoire.services.codex import (
    CodexMatch,
    CodexProduct,
    IdentificationSource,
    MatchType,
)
from grimoire.models import Product


WRONG_PRODUCT = CodexProduct(
    id="9dbf77a5-eaf3-4d1b-9b37-0e58c0df041e",
    title="SoRoPlay GamTools Zine: Zombie Ref",
    publisher="Ken Wickham",
    product_type="bestiary",
)


class _StubClient:
    """Codex client that returns a chosen match for the title fallback."""

    def __init__(self, match):
        self._match = match

    async def is_available(self):
        return True

    async def identify_by_hash(self, file_hash):
        return None  # Codex holds almost no file hashes — the real situation

    async def identify_by_title(self, title, filename=None):
        return self._match


@pytest.fixture
def local_product(db):
    product = Product(
        file_path=r"D:\Games\Zombie Reign\Zombie Reign - V1-1 Pages.pdf",
        file_name="Zombie Reign - V1-1 Pages.pdf",
        file_size=49710665,
        file_hash="f46e13f8e73c623b6096a6d9eac992a576caca415ef3da799783bfbbd3fc3cc2",
        title="Zombie Reign",
        publisher="Angry Engine Games",
    )
    db.add(product)
    return product


def _install(monkeypatch, match):
    monkeypatch.setattr(sync_service, "get_codex_client", lambda **kw: _StubClient(match))

    async def fake_settings(db):
        return True, "test-key"

    monkeypatch.setattr(sync_service, "get_codex_settings_from_db", fake_settings)


@pytest.mark.asyncio
async def test_a_fuzzy_match_does_not_overwrite_the_product(db, local_product, monkeypatch):
    """The Zombie Reign case: a plausible wrong match must write nothing."""
    _install(monkeypatch, CodexMatch(
        match_type=MatchType.FUZZY,
        confidence=0.818,
        product=WRONG_PRODUCT,
        source=IdentificationSource.CODEX_TITLE,
    ))

    result = await sync_service.sync_product_from_codex(
        db=db, product=local_product, overwrite_existing=True
    )

    assert result["synced"] is False
    assert local_product.title == "Zombie Reign"
    assert local_product.publisher == "Angry Engine Games"


@pytest.mark.asyncio
async def test_a_fuzzy_match_is_reported_as_a_suggestion(db, local_product, monkeypatch):
    """Skipping silently would be its own bug — the caller needs to know why."""
    _install(monkeypatch, CodexMatch(
        match_type=MatchType.FUZZY,
        confidence=0.818,
        product=WRONG_PRODUCT,
        source=IdentificationSource.CODEX_TITLE,
    ))

    result = await sync_service.sync_product_from_codex(db=db, product=local_product)

    assert result["reason"] == "fuzzy_match_not_applied"
    assert result["match_type"] == "fuzzy"
    assert result["confidence"] == pytest.approx(0.818)
    assert result["suggested_title"] == "SoRoPlay GamTools Zine: Zombie Ref"


@pytest.mark.asyncio
async def test_a_fuzzy_match_does_not_mark_the_product_identified(db, local_product, monkeypatch):
    """ai_identified drives re-sync eligibility; a guess must not set it."""
    local_product.ai_identified = False
    _install(monkeypatch, CodexMatch(
        match_type=MatchType.FUZZY,
        confidence=0.99,  # high, but still fuzzy
        product=WRONG_PRODUCT,
        source=IdentificationSource.CODEX_TITLE,
    ))

    await sync_service.sync_product_from_codex(db=db, product=local_product)

    assert local_product.ai_identified is False
    assert local_product.identification_confidence is None


@pytest.mark.asyncio
async def test_an_exact_match_still_applies(db, local_product, monkeypatch):
    """The gate must not break the case the feature exists for."""
    _install(monkeypatch, CodexMatch(
        match_type=MatchType.EXACT,
        confidence=1.0,
        product=CodexProduct(
            id="abc",
            title="Zombie Reign",
            publisher="Angry Engine Games",
            product_type="Setting",
            page_count=140,
        ),
        source=IdentificationSource.CODEX_TITLE,
    ))

    result = await sync_service.sync_product_from_codex(db=db, product=local_product)

    assert result["synced"] is True
    assert local_product.page_count == 140
    assert local_product.ai_identified is True
