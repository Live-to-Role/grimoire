"""Tests for backup API routes."""

import pytest
from fastapi.testclient import TestClient
from grimoire.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_get_status_unconfigured(client):
    """GET /api/v1/backups/status returns unconfigured status."""
    response = client.get("/api/v1/backups/status")
    assert response.status_code == 200
    data = response.json()
    assert data["destination_configured"] is False


def test_list_backups_empty(client):
    """GET /api/v1/backups/ returns empty list when no destination."""
    response = client.get("/api/v1/backups/")
    assert response.status_code == 200
    data = response.json()
    assert data["backups"] == []
