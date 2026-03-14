"""Backup API endpoints."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from grimoire.api.deps import DbSession
from grimoire.config import settings as app_settings
from grimoire.schemas.backup import (
    BackupEntry,
    BackupListResponse,
    BackupStatus,
    RestoreSummary,
    SnapshotRequest,
    StorageRecommendation,
)
from grimoire.services.backup import (
    delete_backup,
    full_backup,
    get_backup_settings,
    get_status,
    get_storage_recommendations,
    read_manifest,
    restore_from_full,
    restore_from_snapshot,
    rotate,
    snapshot_db,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_db_path() -> Path:
    """Resolve the path to the live grimoire.db from the database URL."""
    url = app_settings.database_url
    return Path(url.split("///", 1)[1])


async def _get_backup_dir(db: DbSession) -> Path | None:
    """Read backup_destination from settings, return Path or None."""
    s = await get_backup_settings(db)
    dest = s["backup_destination"]
    if dest is None:
        return None
    p = Path(dest)
    if not p.exists():
        return None
    return p


async def _run_rotation(db: DbSession, backup_dir: Path) -> None:
    """Run rotation using current settings."""
    s = await get_backup_settings(db)
    db_ret = s["backup_db_retention_count"]
    full_ret = s["backup_full_retention_count"]
    if db_ret is None or full_ret is None:
        rec = get_storage_recommendations(
            db_size_bytes=_get_db_path().stat().st_size if _get_db_path().exists() else 0,
            derived_size_bytes=0,
            budget_gb=s["backup_max_budget_gb"],
        )
        db_ret = db_ret or rec.recommended_db_retention
        full_ret = full_ret or rec.recommended_full_retention
    await rotate(
        backup_dir=backup_dir,
        db_retention_count=db_ret,
        full_retention_count=full_ret,
        max_budget_bytes=int(s["backup_max_budget_gb"] * 1024**3),
    )


@router.get("/status", response_model=BackupStatus)
async def backup_status(db: DbSession) -> BackupStatus:
    """Get backup system health status and warnings."""
    s = await get_backup_settings(db)
    backup_dir = None
    dest = s["backup_destination"]
    if dest:
        backup_dir = Path(dest) if Path(dest).exists() else None
    return get_status(backup_dir=backup_dir, budget_gb=s["backup_max_budget_gb"])


@router.get("/", response_model=BackupListResponse)
async def list_backups(db: DbSession) -> BackupListResponse:
    """List all backups."""
    backup_dir = await _get_backup_dir(db)
    if backup_dir is None:
        return BackupListResponse(backups=[], total_size_gb=0)
    entries = read_manifest(backup_dir)
    total_gb = round(sum(e.size_bytes for e in entries) / (1024**3), 2)
    return BackupListResponse(backups=entries, total_size_gb=total_gb)


@router.get("/recommendations", response_model=StorageRecommendation)
async def recommendations(
    db: DbSession,
    budget_gb: float = Query(default=100, description="Storage budget in GB"),
) -> StorageRecommendation:
    """Get storage recommendations for a given budget."""
    db_path = _get_db_path()
    db_size = db_path.stat().st_size if db_path.exists() else 0

    derived_size = 0
    for subdir in ("covers", "text", "images"):
        d = app_settings.data_dir / subdir
        if d.exists():
            derived_size += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())

    return get_storage_recommendations(
        db_size_bytes=db_size,
        derived_size_bytes=derived_size,
        budget_gb=budget_gb,
    )


@router.post("/snapshot", response_model=BackupEntry)
async def create_snapshot(db: DbSession, request: SnapshotRequest | None = None) -> BackupEntry:
    """Trigger a manual DB snapshot."""
    backup_dir = await _get_backup_dir(db)
    if backup_dir is None:
        raise HTTPException(status_code=400, detail="Backup destination not configured")

    label = request.label if request else None
    entry = await snapshot_db(db_path=_get_db_path(), backup_dir=backup_dir, label=label)
    await _run_rotation(db, backup_dir)
    return entry


@router.post("/full", response_model=BackupEntry)
async def create_full_backup(db: DbSession) -> BackupEntry:
    """Trigger a manual full backup (DB + derived files)."""
    backup_dir = await _get_backup_dir(db)
    if backup_dir is None:
        raise HTTPException(status_code=400, detail="Backup destination not configured")

    entry = await full_backup(
        db_path=_get_db_path(),
        backup_dir=backup_dir,
        data_dir=app_settings.data_dir,
    )
    await _run_rotation(db, backup_dir)
    return entry


@router.post("/{backup_id}/restore", response_model=RestoreSummary)
async def restore_backup(db: DbSession, backup_id: str) -> RestoreSummary:
    """Restore from a specific backup."""
    from grimoire.database import engine

    backup_dir = await _get_backup_dir(db)
    if backup_dir is None:
        raise HTTPException(status_code=400, detail="Backup destination not configured")

    entries = read_manifest(backup_dir)
    entry = next((e for e in entries if e.id == backup_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Backup not found")

    async def dispose():
        await engine.dispose()

    def recreate():
        pass  # Engine auto-reconnects via pool_pre_ping=True

    try:
        if entry.type == "db":
            return await restore_from_snapshot(
                backup_id=backup_id,
                backup_dir=backup_dir,
                db_path=_get_db_path(),
                dispose_engine=dispose,
                recreate_engine=recreate,
            )
        elif entry.type == "full":
            return await restore_from_full(
                backup_id=backup_id,
                backup_dir=backup_dir,
                db_path=_get_db_path(),
                data_dir=app_settings.data_dir,
                dispose_engine=dispose,
                recreate_engine=recreate,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown backup type: {entry.type}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{backup_id}", status_code=204)
async def remove_backup(db: DbSession, backup_id: str) -> None:
    """Delete a specific backup."""
    backup_dir = await _get_backup_dir(db)
    if backup_dir is None:
        raise HTTPException(status_code=400, detail="Backup destination not configured")
    try:
        await delete_backup(backup_id=backup_id, backup_dir=backup_dir)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
