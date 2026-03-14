"""Backup service for database snapshots and full backups."""

import json
import json as _json
import logging
import tempfile
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
