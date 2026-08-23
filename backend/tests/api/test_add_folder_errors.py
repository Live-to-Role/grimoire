"""Adding a watched folder must say *why* the path was rejected.

"Folder path does not exist" is true but useless: the commonest mistake is
entering a path that belongs to the other deployment mode — /library on a
native install, or a Windows host path inside Docker — and the fix differs
completely between the two.
"""
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from grimoire.database import get_db
from grimoire.main import app
from grimoire.models import WatchedFolder


@pytest.fixture
async def client(db):
    """Client bound to the in-memory fixture, cleaning up rows it commits.

    The create route commits, and a commit outlives the `db` fixture's
    rollback, so the happy-path test would otherwise leave a watched folder
    behind for whatever test runs next.
    """
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()

    await db.execute(delete(WatchedFolder))
    await db.commit()


async def _add(client, path: str):
    async with client as c:
        return await c.post("/api/v1/folders", json={"path": path, "label": "test"})


async def test_container_path_on_native_install_explains_itself(client, monkeypatch):
    """/library on a native install must not just say 'does not exist'."""
    monkeypatch.setattr("grimoire.api.routes.folders.in_container", lambda: False)

    resp = await _add(client, "/library")

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "/library" in detail
    assert "Docker" in detail
    # It must point at the fix, not just restate the failure.
    assert "actual folder path" in detail.lower() or "real path" in detail.lower()


async def test_windows_host_path_inside_docker_explains_itself(client, monkeypatch):
    """A C:\\ path submitted from inside a container is a known mistake."""
    monkeypatch.setattr("grimoire.api.routes.folders.in_container", lambda: True)

    resp = await _add(client, "C:/Users/steve/Documents/RPG")

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "/library" in detail
    assert "PDF_LIBRARY_PATH" in detail


async def test_unmounted_container_path_inside_docker_explains_itself(client, monkeypatch):
    """/library missing *inside* the container means the bind mount never happened."""
    monkeypatch.setattr("grimoire.api.routes.folders.in_container", lambda: True)

    resp = await _add(client, "/library")

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "PDF_LIBRARY_PATH" in detail


async def test_ordinary_missing_path_still_names_the_path(client, monkeypatch):
    """Everything else keeps a plain message that at least names the path."""
    monkeypatch.setattr("grimoire.api.routes.folders.in_container", lambda: False)

    resp = await _add(client, "/no/such/place")

    assert resp.status_code == 400
    assert "/no/such/place" in resp.json()["detail"]


async def test_existing_directory_is_still_accepted(client, tmp_path, monkeypatch):
    """The happy path must not regress."""
    monkeypatch.setattr("grimoire.api.routes.folders.in_container", lambda: False)

    resp = await _add(client, str(tmp_path))

    assert resp.status_code == 201
    assert resp.json()["path"] == str(tmp_path)


async def test_file_instead_of_directory_names_the_path(client, tmp_path, monkeypatch):
    monkeypatch.setattr("grimoire.api.routes.folders.in_container", lambda: False)
    target = tmp_path / "book.pdf"
    target.write_text("not a directory")

    resp = await _add(client, str(target))

    assert resp.status_code == 400
    assert str(target) in resp.json()["detail"]
    assert Path(target).is_file()
