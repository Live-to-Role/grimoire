"""What may be shared with Codex, and what may not.

Codex is for identifications of content somebody can buy elsewhere —
adventures, sourcebooks, zines and other play aids. It is not for collections
of images, maps or tokens.

Nothing enforced that. There is no `is_image_content` check anywhere in the
contribution path — not in `should_contribute`, `queue_contribution`,
`queue_product_for_contribution`, or the manual API route. A map pack or a
stock-art PDF that has been given a title is contributable today, which the
image classifier's own verdict says it should not be. In the live library
**1,710 products are flagged `is_image_content` and every one of them has a
title**, so every one is currently eligible.

This is the image/map half of the predicate. The `file_type != "pdf"` clause
arrives with the column that makes a non-PDF product expressible, in Phase 2
of the multi-format plan — it cannot land here without depending on the work
it is supposed to precede.

Outbound only. Reading *from* Codex sends nothing upstream and stays enabled
for every product.
"""
import inspect

import pytest
from httpx import ASGITransport, AsyncClient

from grimoire.database import get_db
from grimoire.main import app
from grimoire.models import ContributionQueue, Product, Setting
from grimoire.services.codex_eligibility import is_codex_eligible


def _product(**kw):
    base = dict(
        file_path=r"D:\Games\thing.pdf",
        file_name="thing.pdf",
        file_size=1024,
        file_hash="h",
        title="A Thing",
    )
    base.update(kw)
    return Product(**base)


# --- the predicate ---------------------------------------------------------

def test_image_content_is_not_eligible():
    eligible, reason = is_codex_eligible(_product(is_image_content=True))
    assert eligible is False
    assert reason == "image_content"


@pytest.mark.parametrize("product_type", [
    "Map", "map", "Art/Maps", "Stock Art", "Token", "Portrait",
])
def test_image_product_types_are_not_eligible(product_type):
    eligible, reason = is_codex_eligible(_product(product_type=product_type))
    assert eligible is False, f"{product_type} should not be contributable"
    assert reason == "image_content"


@pytest.mark.parametrize("product_type", [
    "Adventure", "Supplement", "Zine", "Core Rulebook", "Bestiary",
    # Play aids are what Codex is *for*, even though they are page-light.
    "Character Sheet", "Handout", "GM Tools",
])
def test_ordinary_products_are_eligible(product_type):
    eligible, reason = is_codex_eligible(_product(product_type=product_type))
    assert eligible is True, f"{product_type} should be contributable"
    assert reason == "eligible"


def test_an_unset_product_type_is_eligible():
    assert is_codex_eligible(_product(product_type=None))[0] is True


# --- both call sites -------------------------------------------------------

class _NeverAsked:
    async def identify_by_hash(self, file_hash):
        raise AssertionError("an ineligible product must not cost a round trip")

    async def is_available(self):
        return True


@pytest.mark.asyncio
async def test_should_contribute_rejects_before_asking_codex(db):
    """Checked before the hash lookup, so an ineligible product costs nothing."""
    from grimoire.services.sync_service import should_contribute

    should, reason = await should_contribute(_product(is_image_content=True), _NeverAsked())

    assert should is False
    assert reason == "image_content"


@pytest.mark.asyncio
async def test_queue_contribution_is_a_real_backstop(db):
    """The single choke point every queued contribution passes through."""
    from grimoire.services.contribution_service import (
        CodexIneligibleError,
        queue_contribution,
    )

    product = _product(product_type="Map")
    db.add(product)
    await db.flush()

    with pytest.raises(CodexIneligibleError):
        await queue_contribution(
            db=db, product_id=product.id, contribution_data={"title": "A Thing"}
        )


@pytest.mark.asyncio
async def test_skip_no_change_check_cannot_smuggle_one_through(db):
    """`skip_no_change_check=True` bypasses should_contribute entirely, which
    is exactly why the guard cannot live only there."""
    from grimoire.services.sync_service import queue_product_for_contribution

    db.add(Setting(key="codex_api_key", value='"test-key"'))
    product = _product(product_type="Stock Art")
    db.add(product)
    await db.commit()

    result = await queue_product_for_contribution(
        db=db, product=product, submit_immediately=False, skip_no_change_check=True
    )

    assert result["success"] is False
    assert result["reason"] == "image_content"
    assert (await db.execute(
        __import__("sqlalchemy").select(ContributionQueue)
    )).scalars().first() is None


# --- the manual route ------------------------------------------------------

@pytest.fixture
def client(db):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_the_manual_route_refuses_with_the_reason(client, db):
    """Naming the reason beats a silent success the user cannot explain."""
    product = _product(product_type="Map")
    db.add(product)
    await db.commit()

    response = await client.post(
        "/api/v1/contributions",
        json={"product_id": product.id, "contribution_data": {"title": "A Thing"}},
    )

    assert response.status_code == 422
    assert "image_content" in response.text


# --- inbound is unaffected -------------------------------------------------

@pytest.mark.asyncio
async def test_reading_from_codex_still_works_for_an_image_product(db, monkeypatch):
    """The rule is about what leaves, not what arrives."""
    from grimoire.services import sync_service
    from grimoire.services.codex import (
        CodexMatch, CodexProduct, IdentificationSource, MatchType,
    )

    product = _product(product_type="Map", publisher=None)
    db.add(product)

    class _Client:
        async def is_available(self):
            return True

        async def identify_by_hash(self, file_hash):
            return CodexMatch(
                match_type=MatchType.EXACT, confidence=1.0,
                product=CodexProduct(id="x", title="A Thing", publisher="Cartographer Co"),
                source=IdentificationSource.CODEX_HASH,
            )

    monkeypatch.setattr(sync_service, "get_codex_client", lambda **kw: _Client())

    async def fake_settings(db):
        return True, "k"

    monkeypatch.setattr(sync_service, "get_codex_settings_from_db", fake_settings)

    result = await sync_service.sync_product_from_codex(db=db, product=product)

    assert result["synced"] is True
    assert product.publisher == "Cartographer Co"


# --- the clause that cannot be written yet ---------------------------------


def _product_columns() -> set[str]:
    return {column.name for column in Product.__table__.columns}


class TestCodexStaysPdfOnly:
    """A tripwire for a rule that currently has nothing enforcing it.

    Codex is PDF-only, permanently — the multi-format work extends what
    Grimoire *catalogues*, never what it *shares*. But `file_type` does not
    exist on `Product` yet, so `is_codex_eligible` cannot check it, and the
    obligation lives only in prose: two plan documents and a docstring, all
    saying the clause must land in the same commit as the column.

    ⚠️ NOTHING MAKES THAT HAPPEN. Add the column in multi-format Phase 2,
    forget the clause, and every non-PDF product Grimoire can now catalogue
    becomes contributable upstream — silently, because Codex trusts this
    side to filter and has deliberately grown no rule of its own.

    So these arm themselves. While the column is absent they hold the
    reminder in place; the moment it appears they demand the behaviour.

    **Two things found by rehearsing it** — the column was added locally,
    the tests were watched to fail, the clause was added, and both were
    reverted:

    1. The clause cannot be a bare `product.file_type != "pdf"` without
       also giving `_product()` above a `file_type`. A SQLAlchemy column
       default applies at INSERT, not to an unsaved instance, so
       `Product(...).file_type` is `None` here and every existing
       image/map test starts failing for the wrong reason — refused as
       `unsupported_file_type` before it reaches the rule it was written
       for. Whoever lands Phase 2 wants both in the same commit.
    2. `test_the_column_is_still_absent` fails *by design* on that day.
       Its message says so. It is a signpost to this class, not a defect.
    """

    def test_the_column_is_still_absent(self):
        """The premise of everything below. If this fails, good — read on."""
        assert "file_type" not in _product_columns(), (
            "`file_type` now exists on Product, so the two tests below are live "
            "rather than dormant. That is the intended path, not a problem."
        )

    def test_a_non_pdf_is_refused_as_soon_as_it_can_exist(self):
        """The clause must arrive with the column, not after it.

        Skipped only while a non-PDF product is inexpressible. It cannot be
        skipped and wrong at the same time: the moment `file_type` exists,
        this runs and fails until `is_codex_eligible` consults it.
        """
        if "file_type" not in _product_columns():
            pytest.skip("`file_type` does not exist yet; nothing can be a non-PDF")

        eligible, reason = is_codex_eligible(_product(file_type="epub"))

        assert eligible is False
        assert reason == "unsupported_file_type"

    def test_a_pdf_is_still_allowed_through(self):
        if "file_type" not in _product_columns():
            pytest.skip("`file_type` does not exist yet")

        eligible, _ = is_codex_eligible(_product(file_type="pdf"))

        assert eligible is True

    def test_the_obligation_is_recorded_where_the_clause_will_go(self):
        """Keeps the reminder attached to the code, not only to the plans.

        A docstring is weak enforcement, which is why the two tests above
        exist — but it is what somebody adding the column actually reads,
        and deleting it should not be silent.
        """
        source = inspect.getsource(is_codex_eligible)

        assert "file_type" in source, (
            "The note about the missing PDF-only clause has gone from "
            "is_codex_eligible. Either the clause landed — in which case "
            "these tests should be live — or the reminder was deleted."
        )
