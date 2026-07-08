# Worker Consolidation + "I'm Working" Mode (Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all heavy `ProcessingQueue` draining out of the API/uvicorn process into a dedicated worker process, make pause cross-process and DB-backed (the "I'm working" mode, which the app starts in), and stop the Huey worker from competing on the queue.

**Architecture:** A new `grimoire.worker.run` process runs the existing `run_queue_worker` loop. The API process no longer runs it. Pause state moves from an in-memory `asyncio.Event` to a `Setting` row (`processing_paused`, default `true`) that both processes read/write. Huey is reduced to folder-scan scheduling. Inline queue-processing API endpoints are removed.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.x async, aiosqlite (WAL), Huey (SqliteHuey), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-07-07-worker-consolidation-design.md`

**Branch:** `feat/worker-consolidation` (already based on current `main`).

**Scope note:** This plan covers the **backend + start scripts** only. The frontend "I'm working" toggle, `/queue/stats` polling, and idle-prompt component are a **separate follow-up plan** (they depend on these endpoints and require frontend-codebase exploration). After this plan lands, the freeze is fixed and pause/resume works via the existing `POST /api/v1/queue/pause|resume` endpoints.

**Test runner:** miniconda Python has pytest; the `.venv` does not. Run tests with:
`C:/Users/mkemi/miniconda3/python.exe -m pytest` from the `backend/` directory.
Baseline before starting: **189 passed, 7 pre-existing failures** (diagnostics, products-list, queue-worker concurrency, scanner-batch, backup-routes). Do not try to fix those; just don't add new failures.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `backend/grimoire/services/queue_processor.py` | Queue drain loop + DB-backed pause helpers | Modify |
| `backend/grimoire/worker/run.py` | Dedicated worker process entrypoint | **Create** |
| `backend/grimoire/main.py` | API app; lifespan no longer starts the worker | Modify |
| `backend/grimoire/worker/tasks.py` | Huey tasks — scan scheduling only | Modify (strip) |
| `backend/grimoire/api/routes/queue.py` | Queue API; DB-backed pause; no inline processing | Modify |
| `backend/tests/test_queue_pause.py` | Pause helper round-trip tests | Rewrite |
| `backend/tests/services/test_worker_pause_gate.py` | Worker honours pause flag | **Create** |
| `backend/tests/test_worker_process_wiring.py` | Worker module import + lifespan/endpoint guards | **Create** |
| `start.bat`, `start.sh` | Launch the dedicated worker process | Modify |

---

## Task 1: DB-backed pause helpers

Add `is_processing_paused` / `set_processing_paused` (backed by a `Setting` row), keeping the old sync functions temporarily so the app still imports. Rewrite the pause test to cover the new helpers.

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py`
- Test (rewrite): `backend/tests/test_queue_pause.py`

- [ ] **Step 1: Rewrite the failing test**

Replace the entire contents of `backend/tests/test_queue_pause.py` with:

```python
"""Tests for DB-backed processing-pause ("I'm working" mode)."""
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from grimoire.models import Setting
from grimoire.services.queue_processor import (
    PROCESSING_PAUSED_KEY,
    is_processing_paused,
    set_processing_paused,
)


@pytest.fixture
def session_maker(engine):
    """A session maker bound to the in-memory test engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_defaults_to_paused_when_unset(session_maker):
    # Ensure no flag row exists in the shared session-scoped engine.
    async with session_maker() as s:
        await s.execute(delete(Setting).where(Setting.key == PROCESSING_PAUSED_KEY))
        await s.commit()

    assert await is_processing_paused(session_maker=session_maker) is True


@pytest.mark.asyncio
async def test_set_and_read_roundtrip(session_maker):
    await set_processing_paused(False, session_maker=session_maker)
    assert await is_processing_paused(session_maker=session_maker) is False

    await set_processing_paused(True, session_maker=session_maker)
    assert await is_processing_paused(session_maker=session_maker) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_queue_pause.py -v`
Expected: FAIL — `ImportError: cannot import name 'PROCESSING_PAUSED_KEY'` (and the helpers).

- [ ] **Step 3: Add `import json` to the top imports of `queue_processor.py`**

In `backend/grimoire/services/queue_processor.py`, the current top imports are:

```python
import asyncio
import logging
import time
from datetime import datetime, UTC
from pathlib import Path
```

Change to:

```python
import asyncio
import json
import logging
import time
from datetime import datetime, UTC
from pathlib import Path
```

- [ ] **Step 4: Add the pause helpers**

In `backend/grimoire/services/queue_processor.py`, immediately after the existing block:

```python
# Pause control — set = running, clear = paused
_pause_event = asyncio.Event()
_pause_event.set()  # Start unpaused


def pause_queue():
    """Pause the queue worker (finishes in-flight tasks, stops fetching new ones)."""
    _pause_event.clear()


def resume_queue():
    """Resume the queue worker."""
    _pause_event.set()


def is_queue_paused() -> bool:
    """Check if the queue is currently paused."""
    return not _pause_event.is_set()
```

add:

```python
# DB-backed "I'm working" pause flag. Stored in the settings table so the API
# process and the dedicated worker process share it across the process boundary.
PROCESSING_PAUSED_KEY = "processing_paused"


async def is_processing_paused(session_maker=None) -> bool:
    """Return whether background processing is paused. Defaults to True (paused).

    Opens its own DB session (or a provided one, for tests) so it works from any
    process. Default-True implements "the app starts paused".
    """
    from grimoire.models import Setting

    maker = session_maker or async_session_maker
    async with maker() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == PROCESSING_PAUSED_KEY)
        )
        setting = result.scalar_one_or_none()

    if setting is None:
        return True
    try:
        return bool(json.loads(setting.value))
    except (json.JSONDecodeError, TypeError):
        return True


async def set_processing_paused(paused: bool, session_maker=None) -> None:
    """Persist the "I'm working" pause flag."""
    from grimoire.models import Setting

    maker = session_maker or async_session_maker
    value = json.dumps(bool(paused))
    async with maker() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == PROCESSING_PAUSED_KEY)
        )
        setting = result.scalar_one_or_none()
        if setting is None:
            session.add(Setting(key=PROCESSING_PAUSED_KEY, value=value))
        else:
            setting.value = value
        await session.commit()
```

(`select` and `async_session_maker` are already imported at the top of this file.)

- [ ] **Step 5: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_queue_pause.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/services/queue_processor.py backend/tests/test_queue_pause.py
git commit -m "feat(queue): add DB-backed processing-pause helpers"
```

---

## Task 2: Worker loop honours the DB pause flag

Switch the worker's pause gate from the in-memory `_pause_event` to `await is_processing_paused()`.

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py` (inside `run_queue_worker`)
- Test: `backend/tests/services/test_worker_pause_gate.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_worker_pause_gate.py`:

```python
"""The worker must not process items while paused."""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_worker_skips_processing_while_paused():
    with patch(
        "grimoire.services.queue_processor.is_processing_paused",
        new=AsyncMock(return_value=True),
    ), patch(
        "grimoire.services.queue_processor.process_queue_item",
        new=AsyncMock(return_value=True),
    ) as mock_proc, patch(
        "grimoire.services.queue_processor.get_pending_batch",
        new=AsyncMock(return_value=[]),
    ) as mock_batch, patch(
        "grimoire.services.queue_processor.async_session_maker"
    ) as mock_session:
        # Mock the startup stuck-item recovery query to return no rows.
        mock_db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        stop_event = asyncio.Event()

        async def stop_soon():
            await asyncio.sleep(1.3)
            stop_event.set()

        from grimoire.services.queue_processor import run_queue_worker

        asyncio.create_task(stop_soon())
        await run_queue_worker(poll_interval=0.05, batch_size=5, stop_event=stop_event)

        mock_proc.assert_not_called()
        mock_batch.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_worker_pause_gate.py -v`
Expected: FAIL — the loop still checks `_pause_event` (which is set/unpaused), so it calls `get_pending_batch`/`process_queue_item`.

- [ ] **Step 3: Swap the pause gate in `run_queue_worker`**

In `backend/grimoire/services/queue_processor.py`, find (inside `run_queue_worker`):

```python
        # Wait if paused (check every second so we can still stop)
        while not _pause_event.is_set():
            if stop_event and stop_event.is_set():
                break
            await asyncio.sleep(1.0)
```

Replace with:

```python
        # Wait while paused ("I'm working" mode). Re-read the DB flag each cycle
        # so the API's pause/resume takes effect across the process boundary.
        while await is_processing_paused():
            if stop_event and stop_event.is_set():
                break
            await asyncio.sleep(1.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/test_worker_pause_gate.py -v`
Expected: PASS (1 passed, ~1.3s).

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/queue_processor.py backend/tests/services/test_worker_pause_gate.py
git commit -m "feat(queue): worker honours DB-backed pause flag"
```

---

## Task 3: Point the queue API at the DB-backed pause

Update `/queue/pause`, `/queue/resume`, and `/queue/stats` to use the async helpers.

**Files:**
- Modify: `backend/grimoire/api/routes/queue.py`

- [ ] **Step 1: Update the stats endpoint's paused read**

In `backend/grimoire/api/routes/queue.py`, find:

```python
    from grimoire.services.queue_processor import is_queue_paused
    return {**stats.model_dump(), "paused": is_queue_paused()}
```

Replace with:

```python
    from grimoire.services.queue_processor import is_processing_paused
    return {**stats.model_dump(), "paused": await is_processing_paused()}
```

- [ ] **Step 2: Update the pause/resume endpoints**

Find:

```python
@router.post("/pause")
async def pause_processing_queue() -> dict:
    """Pause the queue worker. In-flight tasks finish, but no new tasks start."""
    from grimoire.services.queue_processor import pause_queue, is_queue_paused
    pause_queue()
    return {"paused": is_queue_paused()}


@router.post("/resume")
async def resume_processing_queue() -> dict:
    """Resume the queue worker."""
    from grimoire.services.queue_processor import resume_queue, is_queue_paused
    resume_queue()
    return {"paused": is_queue_paused()}
```

Replace with:

```python
@router.post("/pause")
async def pause_processing_queue() -> dict:
    """Enable "I'm working" mode — pause background processing.

    In-flight tasks finish; the worker stops fetching new ones.
    """
    from grimoire.services.queue_processor import set_processing_paused
    await set_processing_paused(True)
    return {"paused": True}


@router.post("/resume")
async def resume_processing_queue() -> dict:
    """Disable "I'm working" mode — resume background processing."""
    from grimoire.services.queue_processor import set_processing_paused
    await set_processing_paused(False)
    return {"paused": False}
```

- [ ] **Step 3: Verify the app still imports**

Run: `cd backend && PYTHONPATH=. .venv/Scripts/python.exe -c "import grimoire.main; print('ok')"`
Expected: prints `ok` (ignore any SECRET_KEY/deprecation warnings).

- [ ] **Step 4: Commit**

```bash
git add backend/grimoire/api/routes/queue.py
git commit -m "feat(queue): API pause/resume/stats use DB-backed flag"
```

---

## Task 4: Remove the old in-memory pause API

Now that nothing references them, delete `_pause_event`, `pause_queue`, `resume_queue`, `is_queue_paused`.

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py`

- [ ] **Step 1: Confirm no remaining callers (only the definitions should remain)**

Run: `grep -rn "pause_queue\|resume_queue\|is_queue_paused\|_pause_event" backend/grimoire backend/tests`
Expected: matches **only** the definitions inside `backend/grimoire/services/queue_processor.py` (the `_pause_event` block and the three functions, ~lines 56–72). There must be **no callers** elsewhere (queue.py, tests, the worker loop). If a caller appears outside that definition block, switch it to the DB-backed helpers before continuing.

- [ ] **Step 2: Delete the old block**

In `backend/grimoire/services/queue_processor.py`, delete exactly:

```python
# Pause control — set = running, clear = paused
_pause_event = asyncio.Event()
_pause_event.set()  # Start unpaused


def pause_queue():
    """Pause the queue worker (finishes in-flight tasks, stops fetching new ones)."""
    _pause_event.clear()


def resume_queue():
    """Resume the queue worker."""
    _pause_event.set()


def is_queue_paused() -> bool:
    """Check if the queue is currently paused."""
    return not _pause_event.is_set()
```

- [ ] **Step 3: Verify import + pause tests still pass**

Run: `cd backend && PYTHONPATH=. .venv/Scripts/python.exe -c "import grimoire.main; print('ok')"`
Then: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_queue_pause.py tests/services/test_worker_pause_gate.py -v`
Expected: `ok`, then 3 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/grimoire/services/queue_processor.py
git commit -m "refactor(queue): remove in-memory pause event (superseded by DB flag)"
```

---

## Task 5: Dedicated worker process entrypoint

Create the process that runs the drain loop out-of-band and forces "start paused".

**Files:**
- Create: `backend/grimoire/worker/run.py`
- Test: `backend/tests/test_worker_process_wiring.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_worker_process_wiring.py`:

```python
"""Guards for the worker-process wiring."""
import asyncio
import importlib


def test_worker_run_module_importable_and_has_main():
    mod = importlib.import_module("grimoire.worker.run")
    assert asyncio.iscoroutinefunction(mod.main)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_worker_process_wiring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'grimoire.worker.run'`.

- [ ] **Step 3: Create the worker entrypoint**

Create `backend/grimoire/worker/run.py`:

```python
"""Dedicated background queue-worker process.

Runs the ProcessingQueue drain loop OUTSIDE the API/uvicorn process so heavy CPU
work (OCR, layout extraction, embeddings) never blocks HTTP handling. This is the
single owner of ProcessingQueue draining.

Launched from start.bat / start.sh as `python -m grimoire.worker.run`.
"""
import asyncio
import signal

from grimoire.database import init_db
from grimoire.logging_config import setup_logging
from grimoire.services.queue_processor import run_queue_worker, set_processing_paused


async def main() -> None:
    setup_logging()
    await init_db()

    # Start paused every launch ("I'm working" mode). The worker only starts when
    # the app starts, so forcing the flag here means the app always opens paused;
    # the user enables background processing when ready.
    await set_processing_paused(True)

    stop_event = asyncio.Event()

    # POSIX: stop cleanly on SIGINT/SIGTERM. Not available on Windows'
    # ProactorEventLoop — there we rely on KeyboardInterrupt below, and the
    # worker's startup "reset stuck processing -> pending" recovers abrupt kills.
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    await run_queue_worker(poll_interval=2.0, batch_size=10, stop_event=stop_event)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_worker_process_wiring.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/worker/run.py backend/tests/test_worker_process_wiring.py
git commit -m "feat(worker): dedicated queue-worker process entrypoint"
```

---

## Task 6: Stop the API process from running the worker

Remove the in-app `run_queue_worker` task from the lifespan.

**Files:**
- Modify: `backend/grimoire/main.py`
- Test: `backend/tests/test_worker_process_wiring.py` (add a guard)

- [ ] **Step 1: Add the failing guard test**

Append to `backend/tests/test_worker_process_wiring.py`:

```python
def test_api_lifespan_does_not_start_queue_worker():
    import inspect
    from grimoire.main import lifespan

    src = inspect.getsource(lifespan)
    assert "run_queue_worker" not in src, "API lifespan must not run the queue worker"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_worker_process_wiring.py::test_api_lifespan_does_not_start_queue_worker -v`
Expected: FAIL — the lifespan currently references `run_queue_worker`.

- [ ] **Step 3: Remove the worker startup from the lifespan**

In `backend/grimoire/main.py`, delete exactly:

```python
    # Start queue worker for PDF processing
    from grimoire.services.queue_processor import run_queue_worker
    queue_stop_event = asyncio.Event()
    queue_task = asyncio.create_task(
        run_queue_worker(
            poll_interval=2.0,
            batch_size=10,
            stop_event=queue_stop_event,
        )
    )
    
```

- [ ] **Step 4: Remove the matching shutdown block**

In `backend/grimoire/main.py`, delete exactly:

```python
    # Stop queue worker
    queue_stop_event.set()
    queue_task.cancel()
    try:
        await queue_task
    except asyncio.CancelledError:
        pass
    
```

- [ ] **Step 5: Run tests + import check**

Run: `cd backend && PYTHONPATH=. .venv/Scripts/python.exe -c "import grimoire.main; print('ok')"`
Then: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_worker_process_wiring.py -v`
Expected: `ok`, then 2 passed.

(Note: `import asyncio` remains used by the lifespan's other tasks — leave the import.)

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/main.py backend/tests/test_worker_process_wiring.py
git commit -m "refactor(api): stop running the queue worker in the API process"
```

---

## Task 7: Reduce Huey to scan scheduling only

Remove Huey's queue-processing overlap and the dead cover/metadata tasks.

**Files:**
- Modify: `backend/grimoire/worker/tasks.py`

- [ ] **Step 1: Remove the `process_queue_task()` trigger inside `scan_folder_task`**

In `backend/grimoire/worker/tasks.py`, find (inside `scan_folder_task`'s `_scan`):

```python
            folder.last_scanned_at = datetime.now(UTC)
            await db.commit()
            
            # Trigger queue processing to handle any queued items
            process_queue_task()

            return result.get("new_count", 0)
```

Replace with:

```python
            folder.last_scanned_at = datetime.now(UTC)
            await db.commit()

            # The dedicated queue worker (grimoire.worker.run) drains the queue
            # continuously; no need to trigger processing here.
            return result.get("new_count", 0)
```

- [ ] **Step 2: Delete the `process_cover` task**

Delete the entire function decorated `@huey.task()` named `process_cover` (from its `@huey.task()` line through its `return run_async(_process())`).

- [ ] **Step 3: Delete the `process_metadata` task**

Delete the entire function decorated `@huey.task()` named `process_metadata` (from its `@huey.task()` line through its `return run_async(_process())`).

- [ ] **Step 4: Delete the `process_queue_task` task**

Delete the entire function decorated `@huey.task()` named `process_queue_task` (from its `@huey.task()` line through its `return run_async(_process())`), including the self-requeue call inside it.

After this, `tasks.py` should retain only: `run_async`, `scan_folder_task`, and `periodic_scan`.

- [ ] **Step 5: Verify no references remain and Huey app still imports**

Run: `grep -rn "process_cover\b\|process_metadata\b\|process_queue_task" backend/grimoire`
Expected: **no matches**.
Run: `cd backend && PYTHONPATH=. .venv/Scripts/python.exe -c "import grimoire.worker.tasks; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/worker/tasks.py
git commit -m "refactor(worker): Huey handles folder scans only (queue owned by worker process)"
```

---

## Task 8: Remove inline queue-processing endpoints

`/queue/process` and `/queue/{item_id}/process` run heavy work in the API process. Remove them.

**Files:**
- Modify: `backend/grimoire/api/routes/queue.py`
- Test: `backend/tests/test_worker_process_wiring.py` (add a guard)

- [ ] **Step 1: Add the failing guard test**

Append to `backend/tests/test_worker_process_wiring.py`:

```python
def test_inline_queue_processing_endpoints_removed():
    from grimoire.main import app

    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/v1/queue/process" not in paths
    assert "/api/v1/queue/{item_id}/process" not in paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_worker_process_wiring.py::test_inline_queue_processing_endpoints_removed -v`
Expected: FAIL — both endpoints currently exist.

- [ ] **Step 3: Delete the `/process` endpoint**

In `backend/grimoire/api/routes/queue.py`, delete exactly:

```python
@router.post("/process")
async def process_queue_items(
    db: DbSession,
    max_items: int = Query(10, ge=1, le=100000, description="Max items to process"),
) -> dict:
    """Process pending items in the queue."""
    from grimoire.services.queue_processor import get_pending_batch, process_queue_item

    items = await get_pending_batch(db, max_items)
    succeeded = 0
    failed = 0

    for item in items:
        success = await process_queue_item(item.id)
        if success:
            succeeded += 1
        else:
            failed += 1

    return {
        "processed": len(items),
        "succeeded": succeeded,
        "failed": failed,
    }
```

- [ ] **Step 4: Delete the `/{item_id}/process` endpoint**

Delete exactly:

```python
@router.post("/{item_id}/process")
async def process_single_item(
    item_id: int,
) -> dict:
    """Process a single queue item immediately."""
    from grimoire.services.queue_processor import process_queue_item
    
    success = await process_queue_item(item_id)
    return {"success": success, "item_id": item_id}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/test_worker_process_wiring.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/api/routes/queue.py backend/tests/test_worker_process_wiring.py
git commit -m "refactor(api): remove inline queue-processing endpoints"
```

---

## Task 9: Launch the dedicated worker from start scripts

**Files:**
- Modify: `start.bat`
- Modify: `start.sh`

- [ ] **Step 1: `start.bat` — add the worker launch and rename the Huey window**

In `start.bat`, find:

```bat
REM Start Huey worker
start "Grimoire Worker" cmd /c "set PYTHONPATH=. && python -m huey.bin.huey_consumer grimoire.worker.tasks.huey -w 2 -k thread"
cd ..
```

Replace with:

```bat
REM Start dedicated queue worker (owns heavy ProcessingQueue draining, out of the API process)
start "Grimoire Queue Worker" cmd /c "set PYTHONPATH=. && python -m grimoire.worker.run"

REM Start Huey worker (folder scan scheduling only)
start "Grimoire Scan Worker" cmd /c "set PYTHONPATH=. && python -m huey.bin.huey_consumer grimoire.worker.tasks.huey -w 2 -k thread"
cd ..
```

- [ ] **Step 2: `start.bat` — update the shutdown taskkill list**

Find:

```bat
taskkill /FI "WINDOWTITLE eq Grimoire Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Grimoire Worker*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Grimoire Frontend*" /F >nul 2>&1
```

Replace with:

```bat
taskkill /FI "WINDOWTITLE eq Grimoire Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Grimoire Queue Worker*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Grimoire Scan Worker*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Grimoire Frontend*" /F >nul 2>&1
```

- [ ] **Step 3: `start.sh` — add the worker launch**

In `start.sh`, find:

```bash
# Start Huey worker
PYTHONPATH=. python3 -m huey.bin.huey_consumer grimoire.worker.tasks.huey -w 2 -k thread &
WORKER_PID=$!
cd ..
```

Replace with:

```bash
# Start dedicated queue worker (owns heavy ProcessingQueue draining, out of the API process)
PYTHONPATH=. python3 -m grimoire.worker.run &
QUEUE_WORKER_PID=$!

# Start Huey worker (folder scan scheduling only)
PYTHONPATH=. python3 -m huey.bin.huey_consumer grimoire.worker.tasks.huey -w 2 -k thread &
WORKER_PID=$!
cd ..
```

- [ ] **Step 4: `start.sh` — include the worker in cleanup**

Find:

```bash
    kill $BACKEND_PID $WORKER_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $WORKER_PID $FRONTEND_PID 2>/dev/null
```

Replace with:

```bash
    kill $BACKEND_PID $QUEUE_WORKER_PID $WORKER_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $QUEUE_WORKER_PID $WORKER_PID $FRONTEND_PID 2>/dev/null
```

- [ ] **Step 5: Commit**

```bash
git add start.bat start.sh
git commit -m "chore(start): launch dedicated queue worker; Huey for scans only"
```

---

## Task 10: Full verification

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && C:/Users/mkemi/miniconda3/python.exe -m pytest -q`
Expected: **the 7 pre-existing failures only** (diagnostics ×2, products-list ×1, queue-worker concurrency ×1, scanner-batch ×1, backup-routes ×2), plus all new tests passing. Net new passing tests: `test_queue_pause` (2), `test_worker_pause_gate` (1), `test_worker_process_wiring` (3). No *new* failures.

- [ ] **Step 2: Manual end-to-end (worker out of process, starts paused)**

From `backend/` with the venv python, in one terminal start the worker:
`PYTHONPATH=. .venv/Scripts/python.exe -m grimoire.worker.run`
It should log the queue worker starting and then idle (paused) — it must NOT begin OCR/embedding.

In another terminal, confirm the flag and toggle:
```
curl -s -X POST http://localhost:8000/api/v1/queue/resume   # {"paused": false}
curl -s http://localhost:8000/api/v1/queue/stats            # "paused": false
curl -s -X POST http://localhost:8000/api/v1/queue/pause     # {"paused": true}
```
After `resume`, the worker terminal should begin draining `pending` items; after `pause`, it should stop fetching new ones once the in-flight task finishes. Ctrl+C stops the worker cleanly.

- [ ] **Step 3: Manual — API stays responsive while the worker runs**

With the worker resumed and draining, hit the API and confirm sub-second responses (contrast with the pre-change 7–15s):
`curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" http://localhost:8000/api/v1/tags`
Expected: `200` in well under 1s.

- [ ] **Step 4: Final commit (if any verification tweaks were needed)**

```bash
git status   # should be clean if no tweaks were required
```

---

## Follow-up (separate plan, not this one)

- **Frontend "I'm working" UI:** the toggle bound to `/queue/pause|resume`, `/queue/stats` polling (replacing reliance on `/queue/events` SSE), and the 30-minute idle prompt. Requires frontend-codebase exploration.
- **Single-process model load for query embedding** (Pi/low-RAM): route semantic-search query embedding off the API process. See spec "Out of Scope / Follow-ups".
