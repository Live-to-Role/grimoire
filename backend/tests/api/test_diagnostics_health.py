"""Diagnostics must explain *why* nothing is processing, not just count rows.

The report exists so a user can paste one blob and have the cause named:
a worker process that never started, a paused queue, an unreachable Ollama,
or a library folder the container cannot see.
"""
from datetime import UTC, datetime, timedelta

from grimoire.api.routes.health import get_diagnostics_data
from grimoire.models import ProcessingQueue, Product, Setting, WatchedFolder
from grimoire.services.queue_processor import (
    PROCESSING_PAUSED_KEY,
    WORKER_HEARTBEAT_KEY,
)


async def _set(db, key: str, value: str) -> None:
    from sqlalchemy import select

    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting is None:
        db.add(Setting(key=key, value=value))
    else:
        setting.value = value
    await db.flush()


async def _queue_pending(db, count: int) -> None:
    product = Product(
        file_name="p.pdf", file_path="/lib/p.pdf", file_size=1, file_hash="h"
    )
    db.add(product)
    await db.flush()
    for _ in range(count):
        db.add(ProcessingQueue(product_id=product.id, task_type="text", status="pending"))
    await db.flush()


async def _diag(db):
    return await get_diagnostics_data(db, check_network=False)


async def test_worker_reported_stopped_when_no_heartbeat(db):
    data = await _diag(db)
    assert data["worker"]["running"] is False
    assert data["worker"]["heartbeat"] is None


async def test_worker_reported_running_on_fresh_heartbeat(db):
    await _set(db, WORKER_HEARTBEAT_KEY, datetime.now(UTC).isoformat())
    data = await _diag(db)
    assert data["worker"]["running"] is True
    assert data["worker"]["seconds_since_heartbeat"] < 60


async def test_worker_reported_stopped_on_stale_heartbeat(db):
    stale = datetime.now(UTC) - timedelta(hours=2)
    await _set(db, WORKER_HEARTBEAT_KEY, stale.isoformat())
    data = await _diag(db)
    assert data["worker"]["running"] is False
    assert data["worker"]["seconds_since_heartbeat"] > 3600


async def test_pending_work_with_no_worker_is_a_problem(db):
    await _queue_pending(db, 38)
    data = await _diag(db)
    problems = " ".join(p["message"] for p in data["problems"])
    assert "worker" in problems.lower()
    assert any(p["severity"] == "error" for p in data["problems"])


async def test_pending_work_while_paused_is_reported_as_paused(db):
    await _set(db, WORKER_HEARTBEAT_KEY, datetime.now(UTC).isoformat())
    await _set(db, PROCESSING_PAUSED_KEY, "true")
    await _queue_pending(db, 38)

    data = await _diag(db)
    assert data["worker"]["paused"] is True
    problems = " ".join(p["message"] for p in data["problems"]).lower()
    assert "paused" in problems
    # A deliberately paused worker is not an error, just a reason.
    assert not any(p["severity"] == "error" for p in data["problems"])


async def test_running_unpaused_worker_with_empty_queue_has_no_problems(db):
    await _set(db, WORKER_HEARTBEAT_KEY, datetime.now(UTC).isoformat())
    await _set(db, PROCESSING_PAUSED_KEY, "false")
    db.add(WatchedFolder(path="/tmp", label="tmp", enabled=True))
    await db.flush()

    data = await _diag(db)
    assert data["problems"] == []


async def test_missing_watched_folder_is_reported(db):
    await _set(db, WORKER_HEARTBEAT_KEY, datetime.now(UTC).isoformat())
    await _set(db, PROCESSING_PAUSED_KEY, "false")
    db.add(WatchedFolder(path="/no/such/library", label="gone", enabled=True))
    await db.flush()

    data = await _diag(db)
    folders = data["library"]["watched_folders"]
    assert folders[0]["exists"] is False
    problems = " ".join(p["message"] for p in data["problems"])
    assert "/no/such/library" in problems


async def test_no_watched_folders_is_reported(db):
    await _set(db, WORKER_HEARTBEAT_KEY, datetime.now(UTC).isoformat())
    await _set(db, PROCESSING_PAUSED_KEY, "false")
    data = await _diag(db)
    problems = " ".join(p["message"] for p in data["problems"]).lower()
    assert "no library folders" in problems


async def test_oldest_pending_age_is_reported(db):
    await _queue_pending(db, 1)
    data = await _diag(db)
    assert data["queue"]["oldest_pending_age_seconds"] is not None


async def test_network_checks_are_skippable(db):
    data = await _diag(db)
    assert data["ai"]["ollama_reachable"] is None


async def test_diagnostics_still_excludes_secrets(db):
    data = await _diag(db)
    blob = repr(data).lower()
    assert "sk-" not in blob
    for key in data["config"]:
        assert "key" not in key.lower() or key.endswith("_set")
        assert "secret" not in key.lower() or key.endswith("_set")
