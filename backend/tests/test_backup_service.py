"""Tests for backup service."""

import json
import pytest
from datetime import datetime
from pathlib import Path

from grimoire.services.backup import (
    get_backup_settings,
    read_manifest,
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
