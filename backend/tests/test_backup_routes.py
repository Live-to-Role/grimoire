"""Tests for backup API routes."""

import pytest
from httpx import ASGITransport, AsyncClient

from grimoire.database import get_db
from grimoire.main import app


@pytest.fixture
def client(db):
    """Test client with the DB dependency pinned to the in-memory fixture.

    Without the override these routes open the *configured* database, so the
    tests passed or failed on whatever happened to be on the developer's disk.
    """
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def test_get_status_unconfigured(client):
    """GET /api/v1/backups/status returns unconfigured status."""
    async with client as c:
        response = await c.get("/api/v1/backups/status")
    assert response.status_code == 200
    data = response.json()
    assert data["destination_configured"] is False


async def test_list_backups_empty(client):
    """GET /api/v1/backups/ returns empty list when no destination."""
    async with client as c:
        response = await c.get("/api/v1/backups/")
    assert response.status_code == 200
    data = response.json()
    assert data["backups"] == []
