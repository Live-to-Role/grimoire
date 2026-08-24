"""One bad product must not take the rest of the sync with it.

Phase 0 observed all three of these against the live API. A matched product
bound a `dict` to a `String(255)` column, `sqlite3.ProgrammingError` surfaced
inside `db.commit()`, and because `sync_all_products` caught per product
without rolling back, the `AsyncSession` stayed inactive — so every product
after it raised `PendingRollbackError` and was tallied as `failed`. A
five-product run made only two `/identify` calls; everything after the first
failure died before reaching the network.

`from_dict` is the fix for the dict itself. These are the guards for the next
reshape: a non-scalar never reaches a scalar column, and a product that fails
never costs the ones behind it.
"""
import pytest
import sqlalchemy as sa

from grimoire.models import Product
from grimoire.services import sync_service
from grimoire.services.codex import (
    CodexMatch,
    CodexProduct,
    IdentificationSource,
    MatchType,
)


def _product(title, publisher=None, **kw):
    return Product(
        file_path=rf"D:\Games\{title}.pdf",
        file_name=f"{title}.pdf",
        file_size=1024,
        file_hash=f"hash-{title}",
        title=title,
        publisher=publisher,
        **kw,
    )


class _StubClient:
    def __init__(self, match):
        self._match = match

    async def is_available(self):
        return True

    async def identify_by_hash(self, file_hash):
        return self._match

    async def identify_by_title(self, title, filename=None):
        return self._match


def _install(monkeypatch, match):
    monkeypatch.setattr(sync_service, "get_codex_client", lambda **kw: _StubClient(match))

    async def fake_settings(db):
        return True, "test-key"

    monkeypatch.setattr(sync_service, "get_codex_settings_from_db", fake_settings)


def _exact(product):
    return CodexMatch(
        match_type=MatchType.EXACT,
        confidence=1.0,
        product=product,
        source=IdentificationSource.CODEX_HASH,
    )


@pytest.mark.asyncio
async def test_a_non_scalar_never_reaches_a_scalar_column(db, monkeypatch):
    """Backstop for the next reshape: degrade, don't raise mid-commit.

    Built directly rather than through `from_dict`, which is what makes this a
    backstop — it has to hold even when the parsing layer has been bypassed or
    has missed a newly-nested field.
    """
    codex_product = CodexProduct(id="x", title="Tomb of Rakoss")
    codex_product.publisher = {"name": "Fire Born Games"}  # type: ignore[assignment]

    local = _product("Tomb of Rakoss")
    db.add(local)
    _install(monkeypatch, _exact(codex_product))

    result = await sync_service.sync_product_from_codex(
        db=db, product=local, overwrite_existing=True
    )

    assert local.publisher is None, "a dict was written to a String column"
    assert result["synced"] is True
    assert "publisher" not in result["updated_fields"]
    assert local.title == "Tomb of Rakoss"


@pytest.mark.asyncio
async def test_one_failing_product_does_not_fail_the_rest(db, monkeypatch):
    """The session-poisoning half: a failed commit must be rolled back."""
    first = _product("Aaa Fails")
    second = _product("Bbb Succeeds")
    db.add_all([first, second])
    await db.commit()

    calls = []
    real = sync_service.sync_product_from_codex

    async def flaky(db, product, overwrite_existing=False):
        calls.append(product.title)
        if product.title == "Aaa Fails":
            # Reproduce the real failure: a bad bind surfacing inside commit().
            product.publisher = {"nested": "object"}
            await db.commit()
        product.publisher = "Applied"
        await db.commit()
        return {"synced": True, "product_id": product.id}

    monkeypatch.setattr(sync_service, "sync_product_from_codex", flaky)

    result = await sync_service.sync_all_products(db=db, only_unidentified=False)

    assert calls == ["Aaa Fails", "Bbb Succeeds"], "the second product was never attempted"
    assert result["failed"] == 1
    assert result["synced"] == 1

    refreshed = (await db.execute(
        sa.select(Product).where(Product.title == "Bbb Succeeds")
    )).scalar_one()
    assert refreshed.publisher == "Applied"


@pytest.mark.asyncio
async def test_check_for_updates_reports_no_difference_for_a_nested_publisher(db, monkeypatch):
    """The second reader of the broken read path, which never commits.

    It builds its own `field_mappings` and compares rather than writes, so the
    type guard above never runs there. Before `from_dict` was fixed it reported
    every matched product's publisher as differing, with a dict as the Codex
    side of the diff.
    """
    local = _product("Tomb of Rakoss", publisher="Fire Born Games")
    db.add(local)

    codex_product = CodexProduct.from_dict({
        "id": "x",
        "title": "Tomb of Rakoss",
        "publisher": {"id": "682b6678", "name": "Fire Born Games", "slug": "fire-born-games"},
    })
    _install(monkeypatch, _exact(codex_product))

    assert await sync_service.check_for_updates(db=db, product=local) is None
