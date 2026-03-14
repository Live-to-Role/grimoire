"""Backup service for database snapshots and full backups."""

import asyncio
import hashlib
import json
import json as _json
import logging
import shutil
import sqlite3 as _sqlite3
import tempfile
import zipfile as _zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.schemas.backup import BackupEntry

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "backup-manifest.json"


def read_manifest(backup_dir: Path) -> list[BackupEntry]:
    """Read backup manifest from disk. Returns empty list if not found."""
    manifest_path = backup_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [BackupEntry(**entry) for entry in data]


def write_manifest(backup_dir: Path, entries: list[BackupEntry]) -> None:
    """Write backup manifest atomically (write temp, then rename)."""
    manifest_path = backup_dir / MANIFEST_FILENAME
    data = [entry.model_dump(mode="json") for entry in entries]
    # Atomic write: write to temp file in same dir, then rename
    fd, tmp_path = tempfile.mkstemp(
        dir=backup_dir, prefix=".manifest-", suffix=".tmp"
    )
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        Path(tmp_path).replace(manifest_path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


_BACKUP_SETTING_DEFAULTS = {
    "backup_destination": None,
    "backup_max_budget_gb": 100,
    "backup_db_retention_count": None,
    "backup_full_retention_count": None,
    "backup_auto_enabled": False,
}


async def get_backup_settings(db: AsyncSession) -> dict:
    """Read all backup settings from DB, falling back to defaults."""
    from grimoire.models import Setting

    result = {}
    for key, default in _BACKUP_SETTING_DEFAULTS.items():
        row = await db.execute(select(Setting).where(Setting.key == key))
        setting = row.scalar_one_or_none()
        if setting:
            try:
                result[key] = _json.loads(setting.value)
            except (_json.JSONDecodeError, TypeError):
                result[key] = default
        else:
            result[key] = default
    return result


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_db_sync(db_path: Path, dest_path: Path) -> None:
    """Perform SQLite backup in a thread-safe way."""
    source = _sqlite3.connect(str(db_path))
    dest = _sqlite3.connect(str(dest_path))
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()


async def snapshot_db(
    db_path: Path,
    backup_dir: Path,
    label: str | None = None,
) -> BackupEntry:
    """Create a consistent DB snapshot using SQLite backup API."""
    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%Y-%m-%dT%H-%M-%S")
    filename = f"grimoire-{timestamp_str}.db"
    rel_path = f"db/{filename}"
    dest_path = backup_dir / rel_path

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    await asyncio.to_thread(_snapshot_db_sync, db_path, dest_path)

    sha256 = await asyncio.to_thread(_compute_sha256, dest_path)
    size_bytes = dest_path.stat().st_size

    entry = BackupEntry(
        id=f"grimoire-{timestamp_str}",
        type="db",
        timestamp=now,
        size_bytes=size_bytes,
        sha256=sha256,
        label=label,
        path=rel_path,
    )

    entries = read_manifest(backup_dir)
    entries.append(entry)
    write_manifest(backup_dir, entries)

    logger.info("DB snapshot created: %s (%s bytes)", filename, size_bytes)
    return entry


def _create_full_backup_zip(
    db_path: Path, dest_zip: Path, data_dir: Path
) -> None:
    """Create zip archive with DB snapshot + derived files (sync, for thread)."""
    with _zipfile.ZipFile(dest_zip, "w", _zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, "grimoire.db")
        for subdir in ("covers", "text", "images"):
            dir_path = data_dir / subdir
            if not dir_path.exists():
                continue
            for file in dir_path.rglob("*"):
                if file.is_file():
                    arcname = f"{subdir}/{file.relative_to(dir_path)}"
                    zf.write(file, arcname)


async def full_backup(
    db_path: Path,
    backup_dir: Path,
    data_dir: Path,
    label: str | None = None,
) -> BackupEntry:
    """Create a full backup: DB snapshot + derived files as zip."""
    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%Y-%m-%dT%H-%M-%S")
    filename = f"grimoire-full-{timestamp_str}.zip"
    rel_path = f"full/{filename}"
    dest_path = backup_dir / rel_path

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    temp_db = backup_dir / f".tmp-snapshot-{timestamp_str}.db"
    try:
        await asyncio.to_thread(_snapshot_db_sync, db_path, temp_db)
        await asyncio.to_thread(_create_full_backup_zip, temp_db, dest_path, data_dir)
    finally:
        temp_db.unlink(missing_ok=True)

    sha256 = await asyncio.to_thread(_compute_sha256, dest_path)
    size_bytes = dest_path.stat().st_size

    entry = BackupEntry(
        id=f"grimoire-full-{timestamp_str}",
        type="full",
        timestamp=now,
        size_bytes=size_bytes,
        sha256=sha256,
        label=label,
        path=rel_path,
    )

    entries = read_manifest(backup_dir)
    entries.append(entry)
    write_manifest(backup_dir, entries)

    logger.info("Full backup created: %s (%s bytes)", filename, size_bytes)
    return entry
