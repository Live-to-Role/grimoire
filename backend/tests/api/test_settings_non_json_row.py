"""Regression: one unreadable settings row must not take down the settings API.

`Setting.value` has two writers with two conventions. Every route in
`api/routes/settings.py` stores JSON and reads it back with `json.loads`, but
the queue worker's heartbeat (`queue_processor._write_heartbeat`) stored a bare
ISO timestamp and read it back with `datetime.fromisoformat`.

A bare timestamp is not JSON — `json.loads("2026-08-24T13:58:52...")` parses
`2026` and then raises `Extra data` on the `-08`. Since `get_settings` decodes
every row to build its response, that single row 500s the whole endpoint, and
`replace_settings` calls `get_settings` to build *its* response — so saving an
unrelated setting (a Codex API key, say) reported "failed to save" from the UI
even though the write had already committed.

Both halves are covered here: the heartbeat is stored as JSON now, and the
read path tolerates a value it cannot decode instead of failing the request.
"""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from grimoire.database import get_db
from grimoire.main import app
from grimoire.models import Setting
from grimoire.services.queue_processor import (
    WORKER_HEARTBEAT_KEY,
    parse_heartbeat,
)


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


LEGACY_HEARTBEAT = "2026-08-24T13:58:52.285277+00:00"


@pytest.mark.asyncio
async def test_get_settings_survives_a_non_json_row(client, db):
    """A legacy bare-timestamp heartbeat must not 500 the endpoint."""
    db.add(Setting(key=WORKER_HEARTBEAT_KEY, value=LEGACY_HEARTBEAT))
    db.add(Setting(key="codex_contribute_enabled", value=json.dumps(True)))
    await db.commit()

    response = await client.get("/api/v1/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["codex_contribute_enabled"] is True
    assert body[WORKER_HEARTBEAT_KEY] == LEGACY_HEARTBEAT


@pytest.mark.asyncio
async def test_saving_a_setting_succeeds_alongside_a_non_json_row(client, db):
    """The actual reported bug: PUT reported failure after committing the write."""
    db.add(Setting(key=WORKER_HEARTBEAT_KEY, value=LEGACY_HEARTBEAT))
    await db.commit()

    response = await client.put("/api/v1/settings", json={"codex_api_key": "sk-test-key"})

    assert response.status_code == 200
    assert response.json()["codex_api_key"] == "sk-test-key"


class _MakerFor:
    """Stand-in for `async_session_maker` that hands back the test's session.

    `touch_worker_heartbeat` commits, and the `db` fixture rolls back at
    teardown, so nothing leaks between tests.
    """

    def __init__(self, db):
        self._db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_heartbeat_is_stored_as_json(db):
    """The source fix: the worker writes JSON like every other settings writer."""
    from sqlalchemy import select

    from grimoire.services.queue_processor import touch_worker_heartbeat

    await touch_worker_heartbeat(session_maker=_MakerFor(db))

    setting = (await db.execute(
        select(Setting).where(Setting.key == WORKER_HEARTBEAT_KEY)
    )).scalar_one()

    # Decodes as JSON like every other row, and is still readable as a timestamp.
    assert isinstance(json.loads(setting.value), str)
    assert parse_heartbeat(setting.value) is not None


@pytest.mark.parametrize("stored", [
    LEGACY_HEARTBEAT,                    # written before the fix
    json.dumps(LEGACY_HEARTBEAT),        # written after it
])
def test_parse_heartbeat_reads_both_encodings(stored):
    """The existing row in every deployed database is the bare form."""
    assert parse_heartbeat(stored) is not None
