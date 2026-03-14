"""End-to-end integration tests for backup system."""

import asyncio
import json
import sqlite3
import pytest
from pathlib import Path

from grimoire.services.backup import (
    snapshot_db,
    full_backup,
    restore_from_snapshot,
    delete_backup,
    read_manifest,
    get_status,
    rotate,
)


@pytest.fixture
def backup_env(tmp_path):
    """Create a complete test environment."""
    db_path = tmp_path / "grimoire.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, title TEXT)")
    for i in range(10):
        conn.execute(f"INSERT INTO products VALUES ({i}, 'Product {i}')")
    conn.commit()
    conn.close()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "covers").mkdir()
    (data_dir / "text").mkdir()
    (data_dir / "images").mkdir()
    for i in range(5):
        (data_dir / "covers" / f"cover{i}.jpg").write_bytes(b"jpg" * 100)
        (data_dir / "text" / f"doc{i}.txt").write_text(f"extracted text {i}")

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "db").mkdir()
    (backup_dir / "full").mkdir()

    return db_path, data_dir, backup_dir


@pytest.mark.asyncio
async def test_full_backup_lifecycle(backup_env):
    """Test: snapshot -> modify -> restore -> verify original state."""
    db_path, data_dir, backup_dir = backup_env

    # 1. Create snapshot
    snap = await snapshot_db(db_path=db_path, backup_dir=backup_dir, label="v1")
    assert snap.type == "db"

    # 2. Modify DB
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM products WHERE id > 5")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 6
    conn.close()

    # Need to wait so pre-restore snapshot gets a different timestamp
    await asyncio.sleep(1.1)

    # 3. Restore
    summary = await restore_from_snapshot(
        backup_id=snap.id,
        backup_dir=backup_dir,
        db_path=db_path,
        dispose_engine=None,
        recreate_engine=None,
    )
    assert summary.product_count == 10

    # 4. Verify pre-restore snapshot exists
    entries = read_manifest(backup_dir)
    pre_restore = [e for e in entries if e.label and "pre-restore" in e.label]
    assert len(pre_restore) == 1

    # 5. Create full backup
    full = await full_backup(
        db_path=db_path, backup_dir=backup_dir, data_dir=data_dir
    )
    assert full.type == "full"

    # 6. Status check
    status = get_status(backup_dir=backup_dir, budget_gb=100)
    assert status.destination_configured is True
    assert status.db_snapshot_count == 2  # snap + pre-restore
    assert status.full_backup_count == 1

    # 7. Rotation
    await rotate(
        backup_dir=backup_dir,
        db_retention_count=1,
        full_retention_count=1,
    )
    entries = read_manifest(backup_dir)
    assert len([e for e in entries if e.type == "db"]) == 1

    # 8. Delete all remaining
    remaining = read_manifest(backup_dir)
    for e in remaining:
        await delete_backup(backup_id=e.id, backup_dir=backup_dir)
    assert read_manifest(backup_dir) == []
