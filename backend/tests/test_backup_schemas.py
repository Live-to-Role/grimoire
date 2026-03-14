"""Tests for backup schemas."""

import pytest
from datetime import datetime

from grimoire.schemas.backup import (
    BackupEntry,
    BackupStatus,
    BackupListResponse,
    StorageRecommendation,
    RestoreSummary,
    SnapshotRequest,
)


def test_backup_entry_required_fields():
    entry = BackupEntry(
        id="grimoire-2026-03-14T10-30-00",
        type="db",
        timestamp=datetime(2026, 3, 14, 10, 30, 0),
        size_bytes=14_000_000_000,
        sha256="abc123",
        label="manual",
        path="/backups/db/grimoire-2026-03-14T10-30-00.db",
    )
    assert entry.id == "grimoire-2026-03-14T10-30-00"
    assert entry.type == "db"


def test_backup_entry_size_gb_computed():
    entry = BackupEntry(
        id="test",
        type="db",
        timestamp=datetime(2026, 3, 14),
        size_bytes=1_073_741_824,  # 1 GB
        sha256="abc",
        label=None,
        path="/backups/db/test.db",
    )
    assert abs(entry.size_gb - 1.0) < 0.01


def test_backup_status_warnings_list():
    status = BackupStatus(
        destination_configured=False,
        destination_path=None,
        destination_available_gb=None,
        last_db_snapshot=None,
        last_full_backup=None,
        total_backup_size_gb=0,
        budget_gb=100,
        budget_used_pct=0,
        db_snapshot_count=0,
        full_backup_count=0,
        warnings=["No backup destination configured"],
    )
    assert len(status.warnings) == 1


def test_snapshot_request_optional_label():
    req = SnapshotRequest()
    assert req.label is None
    req2 = SnapshotRequest(label="before upgrade")
    assert req2.label == "before upgrade"


def test_storage_recommendation():
    rec = StorageRecommendation(
        db_snapshot_size_gb=14.0,
        derived_files_size_gb=3.0,
        recommended_db_retention=5,
        recommended_full_retention=2,
        budget_gb=100,
        explanation="With 100 GB budget: 5 DB snapshots (70 GB) + 2 full backups (34 GB)",
    )
    assert rec.recommended_db_retention == 5


def test_restore_summary():
    summary = RestoreSummary(
        restored_from="grimoire-2026-03-14T10-30-00",
        restored_timestamp=datetime(2026, 3, 14, 10, 30, 0),
        product_count=1234,
        pre_restore_snapshot_id="pre-restore-2026-03-14T11-00-00",
    )
    assert summary.product_count == 1234
