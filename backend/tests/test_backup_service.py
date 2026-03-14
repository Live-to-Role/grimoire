"""Tests for backup service."""

import json
import sqlite3
import zipfile
import pytest
from datetime import datetime
from pathlib import Path

import asyncio

from grimoire.services.backup import (
    full_backup,
    get_backup_settings,
    get_status,
    get_storage_recommendations,
    read_manifest,
    restore_from_snapshot,
    rotate,
    snapshot_db,
    write_manifest,
)
from grimoire.schemas.backup import BackupEntry


@pytest.fixture
def backup_dir(tmp_path):
    """Create a temporary backup directory structure."""
    (tmp_path / "db").mkdir()
    (tmp_path / "full").mkdir()
    return tmp_path


def test_read_manifest_empty(backup_dir):
    """Reading manifest from dir with no manifest returns empty list."""
    entries = read_manifest(backup_dir)
    assert entries == []


def test_write_and_read_manifest(backup_dir):
    """Write entries, read them back."""
    entry = BackupEntry(
        id="grimoire-2026-03-14T10-30-00",
        type="db",
        timestamp=datetime(2026, 3, 14, 10, 30, 0),
        size_bytes=1000,
        sha256="abc123",
        label="test",
        path="db/grimoire-2026-03-14T10-30-00.db",
    )
    write_manifest(backup_dir, [entry])
    entries = read_manifest(backup_dir)
    assert len(entries) == 1
    assert entries[0].id == "grimoire-2026-03-14T10-30-00"
    assert entries[0].sha256 == "abc123"


def test_write_manifest_atomic(backup_dir):
    """Manifest write uses atomic rename (temp file, then rename)."""
    entry = BackupEntry(
        id="test",
        type="db",
        timestamp=datetime(2026, 3, 14),
        size_bytes=100,
        sha256="abc",
        label=None,
        path="db/test.db",
    )
    write_manifest(backup_dir, [entry])

    # Verify the manifest file exists (not a temp file)
    manifest_path = backup_dir / "backup-manifest.json"
    assert manifest_path.exists()

    # Verify content is valid JSON
    data = json.loads(manifest_path.read_text())
    assert len(data) == 1
    assert data[0]["id"] == "test"


@pytest.mark.asyncio
async def test_get_backup_settings_defaults(db):
    """With no settings configured, returns defaults."""
    s = await get_backup_settings(db)
    assert s["backup_destination"] is None
    assert s["backup_max_budget_gb"] == 100
    assert s["backup_auto_enabled"] is False
    assert s["backup_db_retention_count"] is None
    assert s["backup_full_retention_count"] is None


@pytest.fixture
def source_db(tmp_path):
    """Create a source SQLite database with test data."""
    db_path = tmp_path / "source" / "grimoire.db"
    db_path.parent.mkdir()
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO products VALUES (1, 'Test Product')")
    conn.commit()
    conn.close()
    return db_path


@pytest.mark.asyncio
async def test_snapshot_db_creates_file(source_db, backup_dir):
    """snapshot_db creates a .db file in backup_dir/db/."""
    entry = await snapshot_db(
        db_path=source_db,
        backup_dir=backup_dir,
        label="test snapshot",
    )
    assert entry.type == "db"
    assert entry.label == "test snapshot"
    assert entry.size_bytes > 0
    assert len(entry.sha256) == 64
    assert (backup_dir / entry.path).exists()


@pytest.mark.asyncio
async def test_snapshot_db_updates_manifest(source_db, backup_dir):
    """snapshot_db adds entry to manifest."""
    await snapshot_db(db_path=source_db, backup_dir=backup_dir)
    entries = read_manifest(backup_dir)
    assert len(entries) == 1
    assert entries[0].type == "db"


@pytest.mark.asyncio
async def test_snapshot_db_data_integrity(source_db, backup_dir):
    """Snapshot contains the same data as original."""
    entry = await snapshot_db(db_path=source_db, backup_dir=backup_dir)
    backup_path = backup_dir / entry.path
    conn = sqlite3.connect(str(backup_path))
    rows = conn.execute("SELECT title FROM products").fetchall()
    conn.close()
    assert rows == [("Test Product",)]


# --- Task 5: Full Backup ---


@pytest.fixture
def data_dir(tmp_path):
    """Create a data directory with derived files."""
    d = tmp_path / "data"
    d.mkdir()
    (d / "covers").mkdir()
    (d / "covers" / "cover1.jpg").write_bytes(b"fake-jpg-data")
    (d / "text").mkdir()
    (d / "text" / "doc1.txt").write_text("extracted text")
    (d / "images").mkdir()
    (d / "images" / "img1.png").write_bytes(b"fake-png-data")
    return d


@pytest.mark.asyncio
async def test_full_backup_creates_zip(source_db, backup_dir, data_dir):
    entry = await full_backup(db_path=source_db, backup_dir=backup_dir, data_dir=data_dir)
    assert entry.type == "full"
    zip_path = backup_dir / entry.path
    assert zip_path.exists()
    assert zip_path.suffix == ".zip"


@pytest.mark.asyncio
async def test_full_backup_zip_contents(source_db, backup_dir, data_dir):
    entry = await full_backup(db_path=source_db, backup_dir=backup_dir, data_dir=data_dir)
    zip_path = backup_dir / entry.path
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert any(n.endswith(".db") for n in names)
        assert any("covers/" in n for n in names)
        assert any("text/" in n for n in names)
        assert any("images/" in n for n in names)


@pytest.mark.asyncio
async def test_full_backup_updates_manifest(source_db, backup_dir, data_dir):
    await full_backup(db_path=source_db, backup_dir=backup_dir, data_dir=data_dir)
    entries = read_manifest(backup_dir)
    full_entries = [e for e in entries if e.type == "full"]
    assert len(full_entries) == 1


# --- Task 6: Rotation ---


@pytest.mark.asyncio
async def test_rotate_by_count(source_db, backup_dir):
    for i in range(3):
        await snapshot_db(db_path=source_db, backup_dir=backup_dir, label=f"snap-{i}")
        await asyncio.sleep(0.01)

    entries_before = read_manifest(backup_dir)
    assert len(entries_before) == 3

    await rotate(backup_dir=backup_dir, db_retention_count=2, full_retention_count=1)

    entries_after = read_manifest(backup_dir)
    db_entries = [e for e in entries_after if e.type == "db"]
    assert len(db_entries) == 2
    assert db_entries[0].label == "snap-1"
    assert db_entries[1].label == "snap-2"


@pytest.mark.asyncio
async def test_rotate_removes_files(source_db, backup_dir):
    entry = await snapshot_db(db_path=source_db, backup_dir=backup_dir)
    file_path = backup_dir / entry.path
    assert file_path.exists()

    await rotate(backup_dir=backup_dir, db_retention_count=0, full_retention_count=0)

    assert not file_path.exists()
    assert read_manifest(backup_dir) == []


# --- Task 7: Storage Recommendations and Status ---


def test_get_storage_recommendations():
    rec = get_storage_recommendations(
        db_size_bytes=14 * 1024**3,
        derived_size_bytes=3 * 1024**3,
        budget_gb=100,
    )
    assert rec.recommended_db_retention == 5
    assert rec.recommended_full_retention == 1
    assert rec.budget_gb == 100


def test_get_storage_recommendations_small_budget():
    rec = get_storage_recommendations(
        db_size_bytes=14 * 1024**3,
        derived_size_bytes=3 * 1024**3,
        budget_gb=10,
    )
    assert rec.recommended_db_retention >= 1
    assert rec.recommended_full_retention >= 0


def test_get_status_unconfigured():
    status = get_status(backup_dir=None)
    assert status.destination_configured is False
    assert "No backup destination configured" in status.warnings


def test_get_status_configured(backup_dir):
    status = get_status(backup_dir=backup_dir, budget_gb=100)
    assert status.destination_configured is True
    assert status.db_snapshot_count == 0


# --- Task 8: Restore from Snapshot ---


@pytest.mark.asyncio
async def test_restore_from_snapshot(source_db, backup_dir):
    """Restore replaces the DB file with the backup."""
    entry = await snapshot_db(db_path=source_db, backup_dir=backup_dir, label="v1")

    # Ensure next snapshot gets a different timestamp
    await asyncio.sleep(1.1)

    conn = sqlite3.connect(str(source_db))
    conn.execute("INSERT INTO products VALUES (2, 'New Product')")
    conn.commit()
    conn.close()

    conn = sqlite3.connect(str(source_db))
    assert len(conn.execute("SELECT * FROM products").fetchall()) == 2
    conn.close()

    summary = await restore_from_snapshot(
        backup_id=entry.id,
        backup_dir=backup_dir,
        db_path=source_db,
        dispose_engine=None,
        recreate_engine=None,
    )

    assert summary.restored_from == entry.id
    assert summary.product_count == 1


@pytest.mark.asyncio
async def test_restore_creates_pre_restore_snapshot(source_db, backup_dir):
    entry = await snapshot_db(db_path=source_db, backup_dir=backup_dir)

    summary = await restore_from_snapshot(
        backup_id=entry.id,
        backup_dir=backup_dir,
        db_path=source_db,
        dispose_engine=None,
        recreate_engine=None,
    )

    entries = read_manifest(backup_dir)
    pre_restore = [e for e in entries if e.label and "pre-restore" in e.label]
    assert len(pre_restore) == 1
    assert summary.pre_restore_snapshot_id == pre_restore[0].id


@pytest.mark.asyncio
async def test_restore_verifies_integrity(source_db, backup_dir):
    entry = await snapshot_db(db_path=source_db, backup_dir=backup_dir)

    backup_path = backup_dir / entry.path
    backup_path.write_bytes(b"corrupted data")

    with pytest.raises(ValueError, match="integrity"):
        await restore_from_snapshot(
            backup_id=entry.id,
            backup_dir=backup_dir,
            db_path=source_db,
            dispose_engine=None,
            recreate_engine=None,
        )
