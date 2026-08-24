"""Grimoire has to learn what became of a contribution.

`ContributionStatus.REJECTED` exists and nothing ever set it. Nothing re-read
a submitted contribution, so one sat at `SUBMITTED` forever whether it was
approved, rejected, or largely held back — Phase 0 found all 37 rows in the
live queue in exactly that state.

That is not cosmetic, because `queue_product_for_contribution` refuses to
re-contribute a product whose contribution is `PENDING` or `SUBMITTED`. A
rejected contribution therefore blocked its product permanently, with nothing
on the Grimoire side to say why.

The fix has a trap in it. Unblocking on rejection alone means the next sync
re-queues the identical payload, Codex re-rejects it, and this repeats every
sync forever, leaving another rejected row in the moderation queue each time.
Codex's own `duplicate_pending` cannot help — it only guards against a
*pending* twin. So a rejected payload stays un-resent until the local data
actually changes, which is what `payload_hash` is for.
"""
import hashlib
import json

import httpx
import pytest

from grimoire.models import ContributionQueue, ContributionStatus, Product
from grimoire.services import codex as codex_module
from grimoire.services.contribution_service import poll_submitted_contributions
from grimoire.services.sync_service import queue_product_for_contribution


def _codex_returns(monkeypatch, body, status_code=200):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(status_code, json=body)
        )
        return real(*args, **kwargs)

    monkeypatch.setattr(codex_module.httpx, "AsyncClient", factory)


@pytest.fixture
async def submitted(db):
    product = Product(
        file_path=r"D:\Games\Zombie Reign.pdf", file_name="Zombie Reign.pdf",
        file_size=1024, file_hash="f46e13f8", title="Zombie Reign",
    )
    db.add(product)
    await db.flush()
    contribution = ContributionQueue(
        product_id=product.id,
        contribution_data=json.dumps({"title": "Zombie Reign"}),
        file_hash="f46e13f8",
        status=ContributionStatus.SUBMITTED,
        codex_contribution_id="11111111-2222-3333-4444-555555555555",
    )
    db.add(contribution)
    await db.commit()
    return contribution


# --- resolving an outcome --------------------------------------------------

@pytest.mark.asyncio
async def test_an_approved_contribution_becomes_accepted(db, submitted, monkeypatch):
    """Codex says "approved"; Grimoire's enum says ACCEPTED. Do not add a
    fourth spelling."""
    _codex_returns(monkeypatch, {
        "id": submitted.codex_contribution_id,
        "status": "approved",
        "review_notes": "",
        "product": "4d3d631e-4a9e-4fdc-8cc8-2b8b46a2d0cc",
    })

    await poll_submitted_contributions(db, api_key="k")

    assert submitted.status == ContributionStatus.ACCEPTED


@pytest.mark.asyncio
async def test_a_rejected_contribution_becomes_rejected(db, submitted, monkeypatch):
    """Nothing set REJECTED before, so the product was blocked forever."""
    _codex_returns(monkeypatch, {
        "id": submitted.codex_contribution_id,
        "status": "rejected",
        "review_notes": "Duplicate of an existing product",
    })

    await poll_submitted_contributions(db, api_key="k")

    assert submitted.status == ContributionStatus.REJECTED
    assert "Duplicate" in (submitted.error_message or "")


@pytest.mark.asyncio
async def test_a_still_pending_contribution_is_left_alone(db, submitted, monkeypatch):
    _codex_returns(monkeypatch, {
        "id": submitted.codex_contribution_id,
        "status": "pending",
        "review_notes": "",
    })

    await poll_submitted_contributions(db, api_key="k")

    assert submitted.status == ContributionStatus.SUBMITTED


@pytest.mark.asyncio
async def test_held_back_warnings_are_read_from_review_notes(db, submitted, monkeypatch):
    """On the queued path the apply runs at approval, so warnings never appear
    in the submission response. `review_notes` is the only channel."""
    _codex_returns(monkeypatch, {
        "id": submitted.codex_contribution_id,
        "status": "approved",
        "review_notes": "description was held back: differs from a curated value",
    })

    await poll_submitted_contributions(db, api_key="k")

    assert "held back" in (submitted.warnings or "")


@pytest.mark.asyncio
async def test_a_contribution_without_a_codex_id_is_skipped(db, submitted, monkeypatch):
    """Rows submitted before the id column existed — all 37 of the live ones."""
    submitted.codex_contribution_id = None
    await db.commit()

    def explode(*a, **kw):
        raise AssertionError("should not have called Codex without an id")

    monkeypatch.setattr(codex_module.httpx, "AsyncClient", explode)

    result = await poll_submitted_contributions(db, api_key="k")

    assert result["unresolvable"] == 1
    assert submitted.status == ContributionStatus.SUBMITTED


# --- the resend guard ------------------------------------------------------

@pytest.fixture
async def rejected(db):
    from grimoire.models import Setting
    from grimoire.services.sync_service import build_contribution_data

    db.add(Setting(key="codex_api_key", value=json.dumps("test-key")))
    product = Product(
        file_path=r"D:\Games\Zombie Reign.pdf", file_name="Zombie Reign.pdf",
        file_size=1024, file_hash="f46e13f8", title="Zombie Reign",
    )
    db.add(product)
    await db.flush()

    # Fingerprint the payload exactly as the submit path would, which is what
    # makes "has the data changed since?" answerable at all.
    payload = build_contribution_data(product)
    contribution = ContributionQueue(
        product_id=product.id,
        contribution_data=json.dumps(payload),
        file_hash="f46e13f8",
        status=ContributionStatus.REJECTED,
        payload_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    )
    db.add(contribution)
    await db.commit()
    return product, contribution


@pytest.mark.asyncio
async def test_an_unchanged_rejected_payload_is_not_resent(db, rejected, monkeypatch):
    """Otherwise every sync re-queues it and Codex re-rejects it, forever."""
    product, _ = rejected

    result = await queue_product_for_contribution(
        db=db, product=product, submit_immediately=False, skip_no_change_check=True
    )

    assert result["success"] is False
    assert result["reason"] == "rejected_unchanged"


@pytest.mark.asyncio
async def test_a_changed_payload_may_be_resent(db, rejected, monkeypatch):
    """A rejection is about the data, so changing the data clears it."""
    product, _ = rejected
    product.publisher = "Angry Engine Games"  # the user fixed something
    await db.commit()

    result = await queue_product_for_contribution(
        db=db, product=product, submit_immediately=False, skip_no_change_check=True
    )

    assert result["success"] is True
