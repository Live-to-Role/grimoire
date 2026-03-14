"""Pydantic models for backup API requests and responses."""

from datetime import datetime
from pydantic import BaseModel, computed_field


class SnapshotRequest(BaseModel):
    """Request to create a DB snapshot."""
    label: str | None = None


class BackupEntry(BaseModel):
    """A single backup entry from the manifest."""
    id: str
    type: str  # "db" or "full"
    timestamp: datetime
    size_bytes: int
    sha256: str
    label: str | None
    path: str

    @computed_field
    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / (1024**3), 2)


class BackupListResponse(BaseModel):
    """Response for listing backups."""
    backups: list[BackupEntry]
    total_size_gb: float


class BackupStatus(BaseModel):
    """Backup system health status."""
    destination_configured: bool
    destination_path: str | None
    destination_available_gb: float | None
    last_db_snapshot: datetime | None
    last_full_backup: datetime | None
    total_backup_size_gb: float
    budget_gb: float
    budget_used_pct: float
    db_snapshot_count: int
    full_backup_count: int
    warnings: list[str]


class StorageRecommendation(BaseModel):
    """Storage budget recommendations."""
    db_snapshot_size_gb: float
    derived_files_size_gb: float
    recommended_db_retention: int
    recommended_full_retention: int
    budget_gb: float
    explanation: str


class RestoreSummary(BaseModel):
    """Summary returned after a restore operation."""
    restored_from: str
    restored_timestamp: datetime
    product_count: int
    pre_restore_snapshot_id: str
