""""Codex has no match" and "Codex could not be asked" are different answers.

`identify_by_hash` and `identify_by_title` wrapped everything in
`except Exception: return None`, and `should_contribute` reads a `None` match
as `return True, "new_product"`. So a timeout, a 500 or a throttle did not
stall a sync — it silently converted every remaining product into a
new-product contribution for things Codex already holds.

That is the exact failure Codex blames for 919 duplicate products, arriving
from the other direction. Codex softens it by converting a `new_product` whose
`file_hash` it already knows into an `edit_product`, but only for hashes it
has — and Phase 0 established its catalogue carries almost none.

Also here: `/identify` is authenticated now. `IdentifyRateThrottle` subclasses
`AnonRateThrottle`, whose `get_cache_key` returns `None` for an authenticated
request, so sending the token Grimoire already holds removes the 60/minute
per-IP ceiling rather than working around it.
"""
import httpx
import pytest

from grimoire.services import codex as codex_module
from grimoire.services.codex import CodexClient, CodexLookupError
from grimoire.services.sync_service import should_contribute


def _transport(monkeypatch, handler):
    real = httpx.AsyncClient
    seen = {}

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(codex_module.httpx, "AsyncClient", factory)
    return seen


# --- authentication --------------------------------------------------------

@pytest.mark.asyncio
async def test_identify_sends_the_token(monkeypatch):
    """An authenticated request is not throttled by AnonRateThrottle at all."""
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"match": "none"})

    _transport(monkeypatch, handler)

    await CodexClient(api_key="secret-key", use_mock=False).identify_by_hash("h")

    assert captured["auth"] == "Token secret-key"


@pytest.mark.asyncio
async def test_identify_stays_anonymous_without_a_key(monkeypatch):
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"match": "none"})

    _transport(monkeypatch, handler)

    client = CodexClient(api_key=None, use_mock=False)
    client.api_key = None  # config may supply one; this test is about the None path
    await client.identify_by_hash("h")

    assert captured["auth"] is None


# --- no match vs could not ask ---------------------------------------------

@pytest.mark.asyncio
async def test_a_genuine_no_match_returns_none(monkeypatch):
    _transport(monkeypatch, lambda request: httpx.Response(200, json={"match": "none"}))

    assert await CodexClient(api_key="k", use_mock=False).identify_by_hash("h") is None


@pytest.mark.parametrize("status_code", [429, 500, 502])
@pytest.mark.asyncio
async def test_a_failed_lookup_raises_rather_than_reporting_no_match(monkeypatch, status_code):
    _transport(monkeypatch, lambda request: httpx.Response(status_code, json={}))

    with pytest.raises(CodexLookupError):
        await CodexClient(api_key="k", use_mock=False).identify_by_hash("h")


@pytest.mark.asyncio
async def test_a_transport_failure_raises_too(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("no route to host")

    _transport(monkeypatch, handler)

    with pytest.raises(CodexLookupError):
        await CodexClient(api_key="k", use_mock=False).identify_by_title("Zombie Reign")


# --- the consequence the bug actually had ----------------------------------

class _BrokenClient:
    async def identify_by_hash(self, file_hash):
        raise CodexLookupError("throttled")


class _SilentClient:
    async def identify_by_hash(self, file_hash):
        return None


@pytest.mark.asyncio
async def test_a_failed_lookup_does_not_become_a_new_product_contribution(db):
    """The 919-duplicates failure mode, from Grimoire's side."""
    from grimoire.models import Product

    product = Product(
        file_path=r"D:\Games\x.pdf", file_name="x.pdf", file_size=1,
        file_hash="h", title="Zombie Reign",
    )

    should, reason = await should_contribute(product, _BrokenClient())

    assert should is False
    assert reason == "lookup_failed"


@pytest.mark.asyncio
async def test_a_real_no_match_still_contributes(db):
    """The gate must not swallow the case the feature exists for."""
    from grimoire.models import Product

    product = Product(
        file_path=r"D:\Games\x.pdf", file_name="x.pdf", file_size=1,
        file_hash="h", title="Zombie Reign",
    )

    should, reason = await should_contribute(product, _SilentClient())

    assert should is True
    assert reason == "new_product"
