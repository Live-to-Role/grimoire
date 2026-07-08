"""Regression test: GET /queue/stats must expose the `paused` flag over HTTP.

The stats handler returns `{**stats.model_dump(), "paused": ...}` but is annotated
`-> QueueStats`. FastAPI treats that annotation as the response_model and filters
the response through it — so if `QueueStats` lacks a `paused` field, `paused` is
silently stripped from the JSON. The frontend's "I'm working" toggle then reads
`undefined` and can never reflect the real pause state.
"""
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from grimoire.main import app
from grimoire.database import get_db


@pytest.fixture
def client(db):
    """Test client with the DB dependency overridden to the in-memory fixture."""
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_queue_stats_includes_paused(client):
    # Isolate from the real DB: pin the pause helper the endpoint calls.
    with patch(
        "grimoire.services.queue_processor.is_processing_paused",
        new=AsyncMock(return_value=True),
    ):
        async with client as c:
            resp = await c.get("/api/v1/queue/stats")

    assert resp.status_code == 200
    data = resp.json()
    assert "paused" in data, f"'paused' missing from /queue/stats response: {data}"
    assert data["paused"] is True
