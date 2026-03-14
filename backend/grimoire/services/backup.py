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

from typing import Awaitable, Callable

from grimoire.schemas.backup import (
    BackupEntry,
    BackupStatus,
    RestoreSummary,
    StorageRecommendation,
)

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


async def rotate(
    backup_dir: Path,
    db_retention_count: int,
    full_retention_count: int,
    max_budget_bytes: int | None = None,
) -> list[str]:
    """Delete oldest backups exceeding retention limits."""
    entries = read_manifest(backup_dir)
    deleted_ids = []

    db_entries = sorted([e for e in entries if e.type == "db"], key=lambda e: e.timestamp)
    full_entries = sorted([e for e in entries if e.type == "full"], key=lambda e: e.timestamp)

    to_delete = []
    if len(db_entries) > db_retention_count:
        to_delete.extend(db_entries[: len(db_entries) - db_retention_count])
    if len(full_entries) > full_retention_count:
        to_delete.extend(full_entries[: len(full_entries) - full_retention_count])

    for entry in to_delete:
        file_path = backup_dir / entry.path
        file_path.unlink(missing_ok=True)
        entries.remove(entry)
        deleted_ids.append(entry.id)
        logger.info("Rotated backup: %s", entry.id)

    if max_budget_bytes is not None:
        remaining = sorted(entries, key=lambda e: e.timestamp)
        total = sum(e.size_bytes for e in remaining)
        while total > max_budget_bytes and remaining:
            oldest = remaining.pop(0)
            file_path = backup_dir / oldest.path
            file_path.unlink(missing_ok=True)
            entries.remove(oldest)
            total -= oldest.size_bytes
            deleted_ids.append(oldest.id)
            logger.info("Rotated backup (budget): %s", oldest.id)

    write_manifest(backup_dir, entries)
    return deleted_ids


def get_storage_recommendations(
    db_size_bytes: int,
    derived_size_bytes: int,
    budget_gb: float,
) -> StorageRecommendation:
    """Calculate recommended retention counts based on budget. 70% DB, 30% full."""
    db_size_gb = db_size_bytes / (1024**3)
    derived_size_gb = derived_size_bytes / (1024**3)
    full_size_gb = db_size_gb + derived_size_gb

    db_budget = budget_gb * 0.7
    full_budget = budget_gb * 0.3

    db_retention = max(1, int(db_budget / db_size_gb)) if db_size_gb > 0 else 1
    full_retention = max(0, int(full_budget / full_size_gb)) if full_size_gb > 0 else 0

    explanation = (
        f"With {budget_gb} GB budget: "
        f"{db_retention} DB snapshots ({db_retention * db_size_gb:.0f} GB) + "
        f"{full_retention} full backups ({full_retention * full_size_gb:.0f} GB)"
    )

    return StorageRecommendation(
        db_snapshot_size_gb=round(db_size_gb, 2),
        derived_files_size_gb=round(derived_size_gb, 2),
        recommended_db_retention=db_retention,
        recommended_full_retention=full_retention,
        budget_gb=budget_gb,
        explanation=explanation,
    )


def get_status(
    backup_dir: Path | None,
    budget_gb: float = 100,
) -> BackupStatus:
    """Get backup system status and health warnings."""
    warnings = []

    if backup_dir is None:
        return BackupStatus(
            destination_configured=False,
            destination_path=None,
            destination_available_gb=None,
            last_db_snapshot=None,
            last_full_backup=None,
            total_backup_size_gb=0,
            budget_gb=budget_gb,
            budget_used_pct=0,
            db_snapshot_count=0,
            full_backup_count=0,
            warnings=["No backup destination configured"],
        )

    entries = read_manifest(backup_dir)
    db_entries = sorted([e for e in entries if e.type == "db"], key=lambda e: e.timestamp)
    full_entries = sorted([e for e in entries if e.type == "full"], key=lambda e: e.timestamp)

    total_bytes = sum(e.size_bytes for e in entries)
    total_gb = total_bytes / (1024**3)
    budget_used_pct = (total_gb / budget_gb * 100) if budget_gb > 0 else 0

    try:
        disk = shutil.disk_usage(str(backup_dir))
        available_gb = round(disk.free / (1024**3), 1)
    except OSError:
        available_gb = None
        disk = None

    last_db = db_entries[-1].timestamp if db_entries else None
    last_full = full_entries[-1].timestamp if full_entries else None

    # Warnings
    if last_db is not None:
        from datetime import timedelta
        age = datetime.now(timezone.utc) - last_db
        if age > timedelta(days=7):
            warnings.append("No DB snapshot in over 7 days")

    if budget_used_pct > 90:
        warnings.append(f"Budget nearly full ({budget_used_pct:.0f}% used)")

    if available_gb is not None and disk is not None:
        pct_free = (disk.free / disk.total * 100) if disk.total > 0 else 0
        if available_gb < 5 or pct_free < 10:
            warnings.append(f"Destination drive low on space ({available_gb} GB free, {pct_free:.0f}%)")

    # Check for last backup failure
    error_file = backup_dir / ".last-backup-error"
    if error_file.exists():
        error_msg = error_file.read_text(encoding="utf-8").strip()
        if error_msg:
            warnings.append(f"Last backup failed: {error_msg}")

    return BackupStatus(
        destination_configured=True,
        destination_path=str(backup_dir),
        destination_available_gb=available_gb,
        last_db_snapshot=last_db,
        last_full_backup=last_full,
        total_backup_size_gb=round(total_gb, 2),
        budget_gb=budget_gb,
        budget_used_pct=round(budget_used_pct, 1),
        db_snapshot_count=len(db_entries),
        full_backup_count=len(full_entries),
        warnings=warnings,
    )


async def restore_from_snapshot(
    backup_id: str,
    backup_dir: Path,
    db_path: Path,
    dispose_engine: Callable[[], Awaitable[None]] | None,
    recreate_engine: Callable[[], None] | None,
) -> RestoreSummary:
    """Restore database from a snapshot."""
    entries = read_manifest(backup_dir)
    entry = next((e for e in entries if e.id == backup_id), None)
    if entry is None:
        raise ValueError(f"Backup not found: {backup_id}")

    backup_path = backup_dir / entry.path
    if not backup_path.exists():
        raise ValueError(f"Backup file missing: {backup_path}")

    # Verify integrity
    actual_hash = await asyncio.to_thread(_compute_sha256, backup_path)
    if actual_hash != entry.sha256:
        raise ValueError(
            f"Backup integrity check failed for {backup_id}: "
            f"expected {entry.sha256}, got {actual_hash}"
        )

    # Pre-restore safety snapshot
    pre_restore_entry = await snapshot_db(
        db_path=db_path,
        backup_dir=backup_dir,
        label=f"pre-restore-{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S')}",
    )

    # Dispose engine to release all connections
    if dispose_engine:
        await dispose_engine()

    # Copy backup over live DB, remove WAL/SHM
    await asyncio.to_thread(shutil.copy2, backup_path, db_path)
    for suffix in (".db-wal", ".db-shm"):
        wal_path = db_path.with_suffix(suffix)
        if wal_path.exists():
            wal_path.unlink()

    # Recreate engine
    if recreate_engine:
        recreate_engine()

    # Post-restore verification
    def _verify():
        conn = _sqlite3.connect(str(db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            return count
        finally:
            conn.close()

    product_count = await asyncio.to_thread(_verify)

    logger.info(
        "Restored from %s: %d products, pre-restore snapshot: %s",
        backup_id, product_count, pre_restore_entry.id,
    )

    return RestoreSummary(
        restored_from=backup_id,
        restored_timestamp=entry.timestamp,
        product_count=product_count,
        pre_restore_snapshot_id=pre_restore_entry.id,
    )


async def restore_from_full(
    backup_id: str,
    backup_dir: Path,
    db_path: Path,
    data_dir: Path,
    dispose_engine: Callable[[], Awaitable[None]] | None,
    recreate_engine: Callable[[], None] | None,
) -> RestoreSummary:
    """Restore from a full backup (DB + derived files)."""
    entries = read_manifest(backup_dir)
    entry = next((e for e in entries if e.id == backup_id), None)
    if entry is None:
        raise ValueError(f"Backup not found: {backup_id}")
    if entry.type != "full":
        raise ValueError(f"Backup {backup_id} is not a full backup")

    backup_path = backup_dir / entry.path
    if not backup_path.exists():
        raise ValueError(f"Backup file missing: {backup_path}")

    actual_hash = await asyncio.to_thread(_compute_sha256, backup_path)
    if actual_hash != entry.sha256:
        raise ValueError(f"Backup integrity check failed for {backup_id}")

    pre_restore_entry = await snapshot_db(
        db_path=db_path,
        backup_dir=backup_dir,
        label=f"pre-restore-{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S')}",
    )

    if dispose_engine:
        await dispose_engine()

    def _extract():
        with _zipfile.ZipFile(backup_path, "r") as zf:
            for name in zf.namelist():
                if name == "grimoire.db":
                    with zf.open(name) as src, open(db_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                elif name.startswith(("covers/", "text/", "images/")):
                    dest = data_dir / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)

    await asyncio.to_thread(_extract)

    for suffix in (".db-wal", ".db-shm"):
        wal_path = db_path.with_suffix(suffix)
        if wal_path.exists():
            wal_path.unlink()

    if recreate_engine:
        recreate_engine()

    def _verify():
        conn = _sqlite3.connect(str(db_path))
        try:
            return conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        finally:
            conn.close()

    product_count = await asyncio.to_thread(_verify)

    logger.info("Full restore from %s: %d products", backup_id, product_count)

    return RestoreSummary(
        restored_from=backup_id,
        restored_timestamp=entry.timestamp,
        product_count=product_count,
        pre_restore_snapshot_id=pre_restore_entry.id,
    )


async def handle_auto_backup_event(
    db: AsyncSession,
    event: dict,
    event_label: str,
    db_path: Path,
) -> BackupEntry | None:
    """Handle an auto-backup trigger event. Returns BackupEntry if created, None if skipped."""
    settings = await get_backup_settings(db)

    if not settings["backup_auto_enabled"]:
        return None

    dest = settings["backup_destination"]
    if dest is None:
        logger.warning("Auto-backup skipped: no destination configured")
        return None

    backup_dir = Path(dest)
    if not backup_dir.exists():
        logger.warning("Auto-backup skipped: destination does not exist: %s", dest)
        return None

    try:
        entry = await snapshot_db(
            db_path=db_path,
            backup_dir=backup_dir,
            label=f"auto: {event_label}",
        )

        # Run rotation
        db_ret = settings["backup_db_retention_count"]
        full_ret = settings["backup_full_retention_count"]
        if db_ret is None or full_ret is None:
            rec = get_storage_recommendations(
                db_size_bytes=db_path.stat().st_size,
                derived_size_bytes=0,
                budget_gb=settings["backup_max_budget_gb"],
            )
            db_ret = db_ret or rec.recommended_db_retention
            full_ret = full_ret or rec.recommended_full_retention
        await rotate(
            backup_dir=backup_dir,
            db_retention_count=db_ret,
            full_retention_count=full_ret,
            max_budget_bytes=int(settings["backup_max_budget_gb"] * 1024**3),
        )

        # Clear any previous error
        error_file = backup_dir / ".last-backup-error"
        error_file.unlink(missing_ok=True)

        logger.info("Auto-backup completed: %s", entry.id)
        return entry
    except Exception as exc:
        logger.exception("Auto-backup failed")
        error_file = backup_dir / ".last-backup-error"
        error_file.write_text(str(exc), encoding="utf-8")
        return None


async def start_auto_backup_subscriber(db_path: Path, session_factory) -> None:
    """Subscribe to EventBus events and trigger auto-backups.

    Runs as a long-lived background task started during app lifespan.
    """
    from grimoire.services.event_bus import event_bus

    event_labels = {
        "scan_complete": "post-scan",
        "bulk_identify_complete": "post-identification",
        "bulk_embedding_complete": "post-embedding",
        "bulk_extraction_complete": "post-extraction",
    }

    async for event in event_bus.subscribe("backup_triggers"):
        event_type = event.get("type", "")
        label = event_labels.get(event_type)
        if label is None:
            continue

        try:
            async with session_factory() as db:
                await handle_auto_backup_event(
                    db=db, event=event, event_label=label, db_path=db_path,
                )
        except Exception:
            logger.exception("Error in auto-backup subscriber")


async def delete_backup(backup_id: str, backup_dir: Path) -> None:
    """Delete a backup file and its manifest entry."""
    entries = read_manifest(backup_dir)
    entry = next((e for e in entries if e.id == backup_id), None)
    if entry is None:
        raise ValueError(f"Backup not found: {backup_id}")

    file_path = backup_dir / entry.path
    file_path.unlink(missing_ok=True)

    entries = [e for e in entries if e.id != backup_id]
    write_manifest(backup_dir, entries)
    logger.info("Deleted backup: %s", backup_id)
