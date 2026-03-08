"""Tests for the folder browse endpoint."""

import platform
import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from grimoire.main import app


@pytest.fixture
def temp_dirs():
    """Create a temporary directory structure for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "FolderA").mkdir()
        (base / "FolderB").mkdir()
        (base / ".hidden").mkdir()
        yield str(base)


@pytest.mark.asyncio
async def test_browse_default_returns_home():
    """Browse with no path returns home directory."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_path"] == str(Path.home())
    assert isinstance(data["directories"], list)


@pytest.mark.asyncio
async def test_browse_specific_path(temp_dirs):
    """Browse a specific path returns its subdirectories."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": temp_dirs})
    assert resp.status_code == 200
    data = resp.json()
    # Compare resolved paths since the endpoint uses Path.resolve()
    assert data["current_path"] == str(Path(temp_dirs).resolve())
    names = [d["name"] for d in data["directories"]]
    assert "FolderA" in names
    assert "FolderB" in names
    assert ".hidden" not in names


@pytest.mark.asyncio
async def test_browse_nonexistent_path():
    """Browse a nonexistent path returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": "/nonexistent/path/abc123"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_browse_parent_path(temp_dirs):
    """Browse returns correct parent path."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": temp_dirs})
    data = resp.json()
    resolved = Path(temp_dirs).resolve()
    assert data["parent_path"] == str(resolved.parent)


@pytest.mark.asyncio
async def test_browse_sorted_alphabetically(temp_dirs):
    """Directories are sorted alphabetically (case-insensitive)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": temp_dirs})
    data = resp.json()
    names = [d["name"] for d in data["directories"]]
    assert names == sorted(names, key=str.lower)


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only test")
@pytest.mark.asyncio
async def test_browse_my_computer_lists_drives():
    """Browse 'My Computer' lists available Windows drives."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": "My Computer"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_path"] == "My Computer"
    assert data["parent_path"] is None
    names = [d["name"] for d in data["directories"]]
    assert "C:" in names


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only test")
@pytest.mark.asyncio
async def test_browse_drive_root_parent_is_my_computer():
    """On Windows, parent of a drive root is 'My Computer'."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": "C:\\"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["parent_path"] == "My Computer"
