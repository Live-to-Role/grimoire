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


@pytest.mark.asyncio
async def test_browse_skips_unreadable_entries_instead_of_failing(temp_dirs, monkeypatch):
    """One unreadable entry must not take down the whole listing.

    Windows user profiles contain deny-listed junctions ("Application Data",
    "Cookies"); network mounts can go away mid-listing. Either case used to turn
    the entire directory into a 403.
    """
    base = Path(temp_dirs)
    real_is_dir = Path.is_dir

    def flaky_is_dir(self):
        if self.name == "FolderA":
            raise PermissionError("Access is denied")
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", flaky_is_dir)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": str(base)})

    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()["directories"]]
    assert "FolderB" in names
    assert "FolderA" not in names


@pytest.mark.asyncio
async def test_browse_reports_unreadable_directory_with_the_path(temp_dirs, monkeypatch):
    """A 403 must name the directory, so the UI can show something actionable."""
    def denied(self):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(Path, "iterdir", denied)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": temp_dirs})

    assert resp.status_code == 403
    assert str(Path(temp_dirs).resolve()) in resp.json()["detail"]


@pytest.mark.asyncio
async def test_browse_turns_os_errors_into_a_readable_message(temp_dirs, monkeypatch):
    """An unreachable network path must not surface as an opaque 500."""
    def broken(self):
        raise OSError(64, "The specified network name is no longer available")

    monkeypatch.setattr(Path, "iterdir", broken)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": temp_dirs})

    assert resp.status_code == 400
    assert "network name" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_browse_offers_quick_locations():
    """The response carries shortcuts, so a container user can reach /library."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse")

    assert resp.status_code == 200
    locations = resp.json()["locations"]
    assert locations, "expected at least one quick location"
    assert all({"name", "path"} <= set(loc) for loc in locations)
    assert any(loc["path"] == str(Path.home()) for loc in locations)


@pytest.mark.asyncio
async def test_browse_falls_back_when_home_is_unavailable(monkeypatch):
    """A container without a resolvable home must still open the browser."""
    def no_home():
        raise RuntimeError("Could not determine home directory")

    monkeypatch.setattr(Path, "home", staticmethod(no_home))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse")

    assert resp.status_code == 200
    assert resp.json()["current_path"]
