"""Contribution outcomes must be recorded for what they are.

`submit_contribution` treated every non-2xx as `FAILED` and every 2xx as
`SUBMITTED`. Two of Codex's ordinary outcomes are neither:

- `duplicate_pending` — a 400 meaning "you already sent this file hash and it
  is still pending". Entirely benign, recorded as a permanent failure, and the
  `existing_contribution_id` it carries was discarded.
- `no_change` — a **200** meaning "Codex already has everything you sent", so
  it was marked `SUBMITTED` when nothing was submitted, and the
  `existing_product_id` — a free link between the local product and the Codex
  one — was thrown away.

Phase 0 measured why this matters: all 37 rows in the live queue sit at
`SUBMITTED` and none of their hashes are known to Codex. Nothing here can
distinguish "queued for moderation" from "already applied" from "never
arrived".

Also covered: the handle polling needs. `ContributionQueue` had no column for
Codex's contribution id at all, and `submit_contribution` logged the one it
was handed and dropped it.
"""
import json

import httpx
import pytest

from grimoire.models import ContributionQueue, ContributionStatus, Product
from grimoire.services import codex as codex_module
from grimoire.services.codex import CodexClient
from grimoire.services.contribution_service import submit_contribution


def _respond(status_code, body):
    """Route CodexClient's internal AsyncClient at a canned response."""
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(status_code, json=body)
        )
        return real(*args, **kwargs)

    return factory


@pytest.fixture
def codex_returns(monkeypatch):
    def _install(status_code, body):
        monkeypatch.setattr(codex_module.httpx, "AsyncClient", _respond(status_code, body))
    return _install


@pytest.fixture
async def queued(db):
    product = Product(
        file_path=r"D:\Games\Zombie Reign.pdf",
        file_name="Zombie Reign.pdf",
        file_size=1024,
        file_hash="f46e13f8",
        title="Zombie Reign",
    )
    db.add(product)
    await db.flush()
    contribution = ContributionQueue(
        product_id=product.id,
        contribution_data=json.dumps({"title": "Zombie Reign"}),
        file_hash="f46e13f8",
        status=ContributionStatus.PENDING,
        attempts=0,
    )
    db.add(contribution)
    await db.commit()
    return contribution


# --- the two benign outcomes ----------------------------------------------

@pytest.mark.asyncio
async def test_no_change_is_not_recorded_as_submitted(db, queued, codex_returns):
    codex_returns(200, {
        "status": "no_change",
        "message": "Product already has complete data. No contribution needed.",
        "existing_product_id": "4d3d631e-4a9e-4fdc-8cc8-2b8b46a2d0cc",
        "existing_product_title": "Zombie Reign",
    })

    await submit_contribution(db, queued, api_key="k")

    assert queued.status == ContributionStatus.NO_CHANGE
    assert queued.codex_product_id == "4d3d631e-4a9e-4fdc-8cc8-2b8b46a2d0cc"
    assert queued.error_message is None


@pytest.mark.asyncio
async def test_duplicate_pending_is_not_recorded_as_failed(db, queued, codex_returns):
    """A 400 that means "already sent" is benign, and carries a useful id."""
    codex_returns(400, {
        "error": "duplicate_pending",
        "message": "A pending contribution with this file hash already exists",
        "existing_contribution_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    })

    await submit_contribution(db, queued, api_key="k")

    assert queued.status == ContributionStatus.DUPLICATE_PENDING
    assert queued.codex_contribution_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# --- the outcomes that were already right ----------------------------------

@pytest.mark.asyncio
async def test_a_queued_contribution_keeps_its_codex_id(db, queued, codex_returns):
    """The handle polling needs. It was logged and discarded."""
    codex_returns(201, {
        "status": "pending",
        "message": "Contribution submitted for review",
        "contribution_id": "11111111-2222-3333-4444-555555555555",
    })

    await submit_contribution(db, queued, api_key="k")

    assert queued.status == ContributionStatus.SUBMITTED
    assert queued.codex_contribution_id == "11111111-2222-3333-4444-555555555555"


@pytest.mark.asyncio
async def test_apply_warnings_are_kept(db, queued, codex_returns):
    """Codex's guard removes keys that would overwrite; warnings are the only
    signal it happened, and `status` is still "applied"."""
    codex_returns(200, {
        "status": "applied",
        "product_id": "4d3d631e-4a9e-4fdc-8cc8-2b8b46a2d0cc",
        "warnings": [
            "description was held back: differs from a curated value",
            "product_type was held back: differs from a curated value",
        ],
    })

    await submit_contribution(db, queued, api_key="k")

    assert queued.codex_product_id == "4d3d631e-4a9e-4fdc-8cc8-2b8b46a2d0cc"
    assert json.loads(queued.warnings) == [
        "description was held back: differs from a curated value",
        "product_type was held back: differs from a curated value",
    ]


@pytest.mark.asyncio
async def test_a_real_error_is_still_a_failure(db, queued, codex_returns):
    codex_returns(500, {"detail": "boom"})

    await submit_contribution(db, queued, api_key="k")

    assert queued.status == ContributionStatus.FAILED
    assert queued.error_message


# --- the resend guard's raw material ---------------------------------------

@pytest.mark.asyncio
async def test_the_submitted_payload_is_fingerprinted(db, queued, codex_returns):
    """A rejected contribution must not be re-sent until the data changes, so
    what was sent has to be recorded at send time."""
    codex_returns(201, {"status": "pending", "contribution_id": "abc"})

    await submit_contribution(db, queued, api_key="k")

    assert queued.payload_hash
    assert len(queued.payload_hash) == 64  # sha256 hex


# --- the client contract ---------------------------------------------------

@pytest.mark.asyncio
async def test_the_client_reports_a_recognised_400_rather_than_raising(codex_returns):
    """`raise_for_status()` flattened the body into a string and lost the id."""
    codex_returns(400, {
        "error": "duplicate_pending",
        "existing_contribution_id": "aaaa-bbbb",
    })
    client = CodexClient(api_key="k", use_mock=False)

    result = await client.contribute({"title": "x"}, file_hash="h")

    assert result.error_code == "duplicate_pending"
    assert result.existing_contribution_id == "aaaa-bbbb"
