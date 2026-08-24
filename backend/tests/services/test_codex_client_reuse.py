"""Regression: one `/health` call per sync, not one per product.

`sync_product_from_codex` calls `get_codex_client(api_key=...)` for every
product, and the singleton guard read `if _codex_client is None or refresh or
api_key` — so passing a key *always* rebuilt the client. Each rebuild reset
`_available` to `None`, and `is_available()` then issued a fresh `GET /health`.
A sync over the real 19,301-product library therefore cost 19,301 health
checks on top of its 19,301 identify calls, against an endpoint that
rate-limits. Once it started throttling, every remaining product returned
"Codex unavailable" — which `sync_all_products` counts as *skipped*, not
failed, so a sync that did nothing reported a clean run.

The second half matters as much as the first: `_available` was cached with no
expiry, so a single throttled or blipped check disabled Codex for the lifetime
of the process. Reusing the client without a TTL would have turned a
per-product bug into a per-process one.
"""
import httpx
import pytest

from grimoire.services import codex as codex_module
from grimoire.services.codex import (
    CodexClient,
    get_codex_client,
    reset_codex_client,
)


@pytest.fixture(autouse=True)
def _clean_singleton():
    reset_codex_client()
    yield
    reset_codex_client()


class _CountingTransport(httpx.MockTransport):
    """Real httpx, faked socket. Counts /health requests."""

    def __init__(self, status_code=200):
        self.calls = 0
        self.status_code = status_code

        def handler(request):
            self.calls += 1
            return httpx.Response(self.status_code, json={"status": "healthy"})

        super().__init__(handler)


@pytest.fixture
def health(monkeypatch):
    """Route CodexClient's internal AsyncClient through a counting transport."""
    transport = _CountingTransport()
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(codex_module.httpx, "AsyncClient", factory)
    return transport


# --- the singleton ---------------------------------------------------------

def test_same_api_key_reuses_the_client():
    first = get_codex_client(api_key="key-one")
    second = get_codex_client(api_key="key-one")

    assert first is second


def test_changed_api_key_rebuilds_the_client():
    """Saving a new key in Settings must take effect without a restart."""
    first = get_codex_client(api_key="key-one")
    second = get_codex_client(api_key="key-two")

    assert first is not second
    assert second.api_key == "key-two"


def test_refresh_still_rebuilds():
    first = get_codex_client(api_key="key-one")
    second = get_codex_client(api_key="key-one", refresh=True)

    assert first is not second


def test_changed_mock_mode_rebuilds_the_client():
    first = get_codex_client(api_key="key-one", use_mock=False)
    second = get_codex_client(api_key="key-one", use_mock=True)

    assert first is not second
    assert second.use_mock is True


# --- availability caching --------------------------------------------------

@pytest.mark.asyncio
async def test_availability_is_checked_once_across_many_products(health):
    """The actual bug: N products must not cost N health checks."""
    for _ in range(25):
        client = get_codex_client(api_key="key-one")
        assert await client.is_available() is True

    assert health.calls == 1


@pytest.mark.asyncio
async def test_availability_is_rechecked_after_the_ttl(health, monkeypatch):
    """A transient failure must not disable Codex for the process lifetime."""
    now = [1000.0]
    monkeypatch.setattr(codex_module.time, "monotonic", lambda: now[0])

    client = get_codex_client(api_key="key-one")
    assert await client.is_available() is True
    assert health.calls == 1

    now[0] += codex_module.AVAILABILITY_TTL_SECONDS + 1
    assert await client.is_available() is True
    assert health.calls == 2


@pytest.mark.asyncio
async def test_a_failed_check_recovers_after_the_ttl(monkeypatch):
    """The failure mode observed in Phase 0: throttled once, unavailable forever."""
    now = [1000.0]
    monkeypatch.setattr(codex_module.time, "monotonic", lambda: now[0])

    statuses = [429, 200]
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(statuses.pop(0), json={})
        )
        return real(*args, **kwargs)

    monkeypatch.setattr(codex_module.httpx, "AsyncClient", factory)

    client = CodexClient(api_key="key-one")
    assert await client.is_available() is False

    now[0] += codex_module.AVAILABILITY_TTL_SECONDS + 1
    assert await client.is_available() is True
