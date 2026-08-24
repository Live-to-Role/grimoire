"""Metadata is factual and contributable; artwork is the publisher's.

Grimoire sends `cover_image_base64` on every contribution. Many scanned books
came from third parties years ago and their provenance cannot be established,
and for anything Codex already has a cover for, sending one adds nothing.

Two rules covering different halves. "Codex already has one" keys on the
match, so it cannot help for a new_product — where Codex knows nothing and a
scan's cover would otherwise be the first uploaded. Neither rule blocks the
contribution; both drop only the image.
"""
import json

import pytest
from sqlalchemy import select

from grimoire.models import ContributionQueue, Product, Setting
from grimoire.services import sync_service
from grimoire.services.codex import (
    CodexMatch, CodexProduct, IdentificationSource, MatchType,
)
from grimoire.services.codex_eligibility import may_share_cover


def _product(**kw):
    base = dict(
        file_path=r"D:\Games\thing.pdf", file_name="thing.pdf", file_size=1024,
        file_hash="h", title="A Thing", cover_extracted=True,
        cover_image_path=r"D:\covers\1.jpg",
    )
    base.update(kw)
    return Product(**base)


def test_a_scanned_product_may_not_share_its_cover():
    assert may_share_cover(_product(is_scanned=True)) is False


def test_an_ordinary_product_may():
    assert may_share_cover(_product(is_scanned=False)) is True


class _Client:
    def __init__(self, cover_url=None, match=True):
        self._cover_url = cover_url
        self._match = match

    async def is_available(self):
        return True

    async def identify_by_hash(self, file_hash):
        if not self._match:
            return None
        return CodexMatch(
            match_type=MatchType.EXACT, confidence=1.0,
            product=CodexProduct(id="x", title="A Thing", cover_url=self._cover_url),
            source=IdentificationSource.CODEX_HASH,
        )

    async def identify_by_title(self, title, filename=None):
        return await self.identify_by_hash(None)


def _stub(monkeypatch, client):
    """`get_cover_image_base64` reads a real file and returns None when it is
    missing, so without stubbing it every assertion below would pass whether or
    not the rules work. It is imported *inside* `build_contribution_data`, so
    the patch targets `contribution_service`, where it is looked up at call
    time."""
    from grimoire.services import contribution_service

    monkeypatch.setattr(
        contribution_service, "get_cover_image_base64", lambda product: "BASE64DATA"
    )
    monkeypatch.setattr(sync_service, "get_codex_client", lambda **kw: client)


async def _queue(db, product, client, monkeypatch):
    _stub(monkeypatch, client)
    db.add(Setting(key="codex_api_key", value='"test-key"'))
    db.add(product)
    await db.commit()

    await sync_service.queue_product_for_contribution(
        db=db, product=product, submit_immediately=False, skip_no_change_check=True
    )
    row = (await db.execute(select(ContributionQueue))).scalars().one()
    return json.loads(row.contribution_data)


@pytest.mark.asyncio
async def test_an_ordinary_product_still_sends_its_cover(db, monkeypatch):
    """The control. Without it the assertions below prove nothing."""
    payload = await _queue(db, _product(), _Client(cover_url=None), monkeypatch)

    assert payload["cover_image_base64"] == "BASE64DATA"


@pytest.mark.asyncio
async def test_no_cover_is_sent_when_codex_already_has_one(db, monkeypatch):
    payload = await _queue(
        db, _product(), _Client(cover_url="https://images/x.jpg"), monkeypatch
    )

    assert "cover_image_base64" not in payload


@pytest.mark.asyncio
async def test_no_cover_is_sent_for_a_scan_codex_does_not_know(db, monkeypatch):
    """The new_product case the first rule cannot reach."""
    payload = await _queue(db, _product(is_scanned=True), _Client(match=False), monkeypatch)

    assert "cover_image_base64" not in payload


@pytest.mark.asyncio
async def test_a_local_edit_also_withholds_a_scan_cover(db, monkeypatch):
    """The second build site. Missed by the first draft of this plan: editing a
    scanned product locally and syncing the edit would still have uploaded the
    cover, with no test covering that path."""
    _stub(monkeypatch, _Client(match=False))
    product = _product(is_scanned=True)
    db.add(Setting(key="codex_api_key", value='"test-key"'))
    # This path also gates on contribute_enabled, which the queue path does not.
    db.add(Setting(key="codex_contribute_enabled", value="true"))
    db.add(product)
    await db.commit()

    await sync_service.queue_local_edit_for_sync(
        db=db, product=product, edited_fields={"publisher": "Fixed By Hand"}
    )

    row = (await db.execute(select(ContributionQueue))).scalars().one()
    payload = json.loads(row.contribution_data)
    assert payload["publisher"] == "Fixed By Hand"
    assert "cover_image_base64" not in payload


@pytest.mark.asyncio
async def test_a_scan_costs_no_lookup(db):
    """`may_share_cover` short-circuits: no answer from Codex would change the
    result, so a scan must not spend a round trip asking."""
    from grimoire.services.sync_service import resolve_include_cover

    class _Explodes:
        async def identify_by_hash(self, file_hash):
            raise AssertionError("a scan must not cost an /identify call")

    assert await resolve_include_cover(_product(is_scanned=True), _Explodes()) is False
