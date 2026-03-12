"""Tests for semantic search-status endpoint."""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch

from grimoire.main import app
from grimoire.database import get_db


@pytest.fixture
def client(db):
    """Create test client with DB dependency override."""
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_search_status_default_disabled(client, db):
    """search-status returns enabled=false when no provider is configured."""
    async with client as c:
        response = await c.get("/api/v1/semantic/search-status")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["provider"] == "none"


@pytest.mark.asyncio
async def test_search_status_with_provider(client, db):
    """search-status returns enabled=true when provider is set and has embeddings."""
    from grimoire.models import Setting
    setting = Setting(key="semantic_search_provider", value='"ollama"')
    db.add(setting)
    await db.commit()

    with patch("grimoire.api.routes.semantic.check_provider_available", return_value=True):
        with patch("grimoire.api.routes.semantic._count_embedded_products", return_value=5):
            async with client as c:
                response = await c.get("/api/v1/semantic/search-status")
    data = response.json()
    assert data["enabled"] is True
    assert data["provider"] == "ollama"
    assert data["has_embeddings"] is True
    assert data["embedded_count"] == 5
