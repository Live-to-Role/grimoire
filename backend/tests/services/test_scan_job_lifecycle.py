"""Tests for ScanJob lifecycle handoff between the API route and the worker task.

The route creates a ScanJob in `pending` and hands off to a Huey task. If the
task never advances the job, `get_active_scan_job` sees it forever and every
later POST /library/scan returns 409.
"""

import pytest
import fitz
from sqlalchemy import delete, select

from grimoire.models import Product, ScanJob, ScanJobStatus, WatchedFolder
from grimoire.services.batch_scanner import (
    get_active_scan_job,
    run_scan_job,
    run_scan_job_by_id,
)


def _make_pdf(directory, name: str) -> None:
    """Write a minimal one-page PDF so the scanner has a real file to hash."""
    directory.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), f"Scan job fixture {name}", fontsize=18)
    doc.save(str(directory / name))
    doc.close()


async def _make_folder(db, path) -> WatchedFolder:
    folder = WatchedFolder(path=str(path), label=str(path), enabled=True)
    db.add(folder)
    await db.flush()
    return folder


async def _make_job(db, folder_id=None) -> ScanJob:
    job = ScanJob(watched_folder_id=folder_id, status=ScanJobStatus.PENDING.value)
    db.add(job)
    await db.flush()
    return job


@pytest.mark.asyncio
async def test_run_scan_job_completes_the_job(db, tmp_path):
    """A successful scan must leave the job in a terminal `complete` state."""
    folder_path = tmp_path / "complete"
    _make_pdf(folder_path, "one.pdf")
    folder = await _make_folder(db, folder_path)
    job = await _make_job(db, folder.id)

    await run_scan_job(db, job, [folder])

    assert job.status == ScanJobStatus.COMPLETE.value
    assert job.is_running is False
    assert job.started_at is not None
    assert job.completed_at is not None
    assert job.new_products == 1
    assert folder.last_scanned_at is not None


@pytest.mark.asyncio
async def test_completed_job_no_longer_blocks_new_scans(db, tmp_path):
    """After the task finishes, get_active_scan_job must report nothing active."""
    await db.execute(delete(ScanJob))
    await db.commit()

    folder_path = tmp_path / "unblock"
    _make_pdf(folder_path, "two.pdf")
    folder = await _make_folder(db, folder_path)
    job = await _make_job(db, folder.id)

    assert await get_active_scan_job(db) is not None  # blocked while pending

    await run_scan_job(db, job, [folder])

    assert await get_active_scan_job(db) is None


@pytest.mark.asyncio
async def test_run_scan_job_aggregates_multiple_folders(db, tmp_path):
    """One job covering several folders sums their counts, not overwrites them."""
    first_path = tmp_path / "multi_a"
    second_path = tmp_path / "multi_b"
    _make_pdf(first_path, "a1.pdf")
    _make_pdf(second_path, "b1.pdf")
    _make_pdf(second_path, "b2.pdf")

    first = await _make_folder(db, first_path)
    second = await _make_folder(db, second_path)
    job = await _make_job(db)

    await run_scan_job(db, job, [first, second])

    assert job.status == ScanJobStatus.COMPLETE.value
    assert job.new_products == 3
    assert first.last_scanned_at is not None
    assert second.last_scanned_at is not None


@pytest.mark.asyncio
async def test_run_scan_job_marks_job_failed_when_scan_raises(db, tmp_path, monkeypatch):
    """A crashing scan must still reach a terminal state, with the error recorded."""
    folder_path = tmp_path / "boom"
    _make_pdf(folder_path, "boom.pdf")
    folder = await _make_folder(db, folder_path)
    job = await _make_job(db, folder.id)

    async def _explode(*args, **kwargs):
        raise RuntimeError("disk went away")

    monkeypatch.setattr("grimoire.services.batch_scanner.scan_folder", _explode)

    await run_scan_job(db, job, [folder])

    assert job.status == ScanJobStatus.FAILED.value
    assert job.is_running is False
    assert job.completed_at is not None
    assert "disk went away" in (job.error_message or "")


@pytest.mark.asyncio
async def test_run_scan_job_continues_after_one_folder_fails(db, tmp_path, monkeypatch):
    """A bad folder must not strand the remaining folders in the same job."""
    bad_path = tmp_path / "bad"
    good_path = tmp_path / "good"
    _make_pdf(bad_path, "bad.pdf")
    _make_pdf(good_path, "good.pdf")

    bad = await _make_folder(db, bad_path)
    good = await _make_folder(db, good_path)
    job = await _make_job(db)

    from grimoire.services import batch_scanner

    real_scan_folder = batch_scanner.scan_folder

    async def _explode_on_bad(session, folder, force=False):
        if folder.id == bad.id:
            raise RuntimeError("unreadable folder")
        return await real_scan_folder(session, folder, force=force)

    monkeypatch.setattr(batch_scanner, "scan_folder", _explode_on_bad)

    await run_scan_job(db, job, [bad, good])

    assert job.status == ScanJobStatus.COMPLETE.value
    assert job.errors == 1
    assert job.new_products == 1
    result = await db.execute(
        select(Product).where(Product.file_path == str(good_path / "good.pdf"))
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_run_scan_job_by_id_resolves_ids_and_completes(db, tmp_path):
    """The worker only gets ids across the process boundary, not ORM objects."""
    folder_path = tmp_path / "by_id"
    _make_pdf(folder_path, "byid.pdf")
    folder = await _make_folder(db, folder_path)
    job = await _make_job(db, folder.id)
    await db.commit()

    await run_scan_job_by_id(db, job.id, [folder.id])

    await db.refresh(job)
    assert job.status == ScanJobStatus.COMPLETE.value
    assert job.new_products == 1


@pytest.mark.asyncio
async def test_run_scan_job_by_id_is_a_noop_for_a_missing_job(db):
    """A deleted job must not crash the worker task."""
    await run_scan_job_by_id(db, 999_999, [])


@pytest.mark.asyncio
async def test_get_active_scan_job_tolerates_multiple_stuck_jobs(db):
    """Two active jobs must not blow up the status endpoint."""
    await db.execute(delete(ScanJob))
    await db.commit()

    older = await _make_job(db)
    newer = await _make_job(db)
    await db.commit()

    active = await get_active_scan_job(db)

    assert active is not None
    assert active.id in (older.id, newer.id)
