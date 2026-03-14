"""Backup service for database snapshots and full backups."""

import json
import logging
import tempfile
from pathlib import Path

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
