# Background Processing Worker Consolidation + "I'm Working" Mode

**Date:** 2026-07-07
**Status:** Design approved, pending spec review

## Problem

Heavy background processing (OCR, layout-mode text extraction, local embedding
generation) runs *inside* the FastAPI/uvicorn process via the in-app asyncio
`run_queue_worker` started in `main.py`'s lifespan. Because it shares the API
process's single GIL, CPU-heavy work in worker threads starves the event loop,
making the whole UI unusable (even a trivial `GET /` takes 7–15s; the library
loads in slow chunks).

Compounding this, a **second** processor — the Huey worker's `process_queue_task`
— drains the *same* `ProcessingQueue` table from a separate process. The two
compete on the SQLite write lock (the reason `_commit_with_retry` exists) and
duplicate effort.

The trigger was enabling the heavier extraction pipeline (pymupdf4llm layout
mode + dynamic OCR) and installing a working `sentence-transformers`, which
switched on an aggressive embedding backfill.

## Goals

- Get **all** heavy processing out of the API process so the UI stays
  responsive at all times.
- Establish a **single owner** for `ProcessingQueue` draining (no more dual
  workers fighting over one SQLite table).
- Give the single user explicit control via an **"I'm working" mode** that
  pauses background processing; the app **starts paused**.
- Nudge the user to enable processing after a period of inactivity.

## Non-Goals

- Live per-task progress streaming to the browser from an out-of-process worker
  (SSE bridge). Replaced by polling; a real bridge is a future follow-up.
- `sqlite-vec` indexed vector search (separate, tracked independently).
- Auto-resume on idle (we prompt, we do not auto-start).
- Any change to task *handler* logic (extraction/OCR/embed handlers are untouched).
- Multi-user pause semantics (single user).

## Architecture: Process Topology

| Process | Responsibility | Change |
|---|---|---|
| **API** (uvicorn) | HTTP + SSE only | Remove in-app queue worker + inline processing |
| **Queue worker** (`python -m grimoire.worker.run`) | Owns ALL `ProcessingQueue` draining | **New process** |
| **Huey** | Folder scan scheduling only (`scan_folder_task`, `periodic_scan`) | Strip queue-processing overlap |
| **Frontend** (vite) | UI, "I'm working" toggle, idle detector | New toggle + idle prompt |

`start.bat` / `start.sh` launch: backend, **queue worker (new)**, huey (scans),
frontend.

Rationale for a dedicated process (vs. Huey-as-owner or in-process
ProcessPool): reuses the existing, feature-complete `run_queue_worker` loop
(auto-requeue, stuck-item recovery, batch logging) essentially unchanged, and
keeps the API process completely free of heavy work. SQLite is already in WAL
mode with a 30s `busy_timeout`, so a single writer process plus the API's reads
do not block each other.

## Detailed Design

### 1. Dedicated worker process

New module `grimoire/worker/run.py`:

- `setup_logging()`, `await init_db()` (ensures schema + pragmas in this process).
- **Force `processing_paused = true`** before entering the loop (implements
  "start paused"; deterministic because the worker only starts at app start).
- Run `run_queue_worker(stop_event=...)`.
- Install SIGINT/SIGTERM handlers that set the stop event for graceful
  shutdown. Abrupt kills are already recovered by the loop's existing "reset
  stuck `processing` → `pending`" step on next startup.

`run_queue_worker` itself is reused as-is except for the pause check (below).

### 2. Remove competing heavy-work paths

- `main.py` lifespan: **remove** the `run_queue_worker` task creation and its
  shutdown handling. Keep the light subscribers (contribution queue processor,
  auto-backup).
- `worker/tasks.py`: **remove** `process_queue_task` and the
  `process_queue_task()` call inside `scan_folder_task`. Also remove the now-dead
  `process_cover` / `process_metadata` Huey tasks (cover is a `ProcessingQueue`
  task type handled by the worker). Keep `scan_folder_task` + `periodic_scan`.
  Verify no other callers during implementation.
- `routes/queue.py`: **remove** `POST /queue/process` and
  `POST /queue/{id}/process` (they run `process_queue_item` inline in the API
  process). Enqueue endpoints (`/queue`, `/queue/batch`, `/queue/*/queue-all`)
  remain; the worker drains them.

### 3. "I'm working" mode (cross-process pause)

- New `Setting` key **`processing_paused`** (boolean, default **`true`**).
  Replaces the in-memory `asyncio.Event` `_pause_event`, which cannot cross
  process boundaries.
- `queue_processor.py` pause API becomes DB-backed, opening its own session via
  `async_session_maker` so existing route signatures are unchanged:
  - `async def set_processing_paused(paused: bool)` — writes the Setting.
  - `async def is_processing_paused() -> bool` — reads the Setting (default
    `true` if unset).
  - `pause_queue()` / `resume_queue()` / `is_queue_paused()` are updated to use
    these (or replaced by the async equivalents at their call sites).
- The worker loop checks `is_processing_paused()` each poll cycle (~2s). When
  paused: finish the in-flight task, stop fetching new items, sleep, re-check.
  Same user-visible semantics as today, now durable and cross-process.
- Existing endpoints keep working: `POST /queue/pause`, `POST /queue/resume`,
  and `GET /queue/stats` (which reports `paused`).

### 4. Activity detector & idle prompt (frontend)

- The browser tracks genuine user activity: `mousemove`, `keydown`, `click`,
  `visibilitychange`. (Backend cannot detect idle because the frontend polls
  `/queue/stats` continuously.)
- After **30 minutes** with no activity, show a **dismissible prompt**:
  "You've been idle — start background processing?" with actions **Start**
  (calls `POST /queue/resume`) and **Dismiss**.
- The idle timer resets on any tracked activity. The prompt does not reappear
  until another full idle interval elapses after dismissal.
- Threshold is a named frontend constant (`IDLE_PROMPT_MINUTES = 30`).
- Not shown while already resumed (processing running).

### 5. Progress display via polling

- The out-of-process worker's `event_bus` events do not reach the API's SSE
  clients. The frontend **polls `GET /queue/stats`** (counts + `paused`) every
  few seconds for queue status instead of subscribing to `/queue/events`.
- `/queue/events` is left in place (harmless) but no longer relied upon. A true
  cross-process event bridge is a documented follow-up.

### 6. "I'm working" toggle (frontend)

- A prominent switch bound to `paused` from `/queue/stats`: ON ⇒ "I'm working"
  (`POST /queue/pause`), OFF ⇒ processing runs (`POST /queue/resume`).
- Reflects state from the polled stats so it stays correct across reloads.

## Data Changes

- One new `Setting` row: `processing_paused` (default `true`). No schema
  migration — the `settings` table already exists.

## Testing

- **Pause round-trip:** `set_processing_paused` / `is_processing_paused` persist
  and read back via the DB fixture; default is `true` when unset.
- **Worker respects pause:** with the flag `true`, the worker's poll step does
  not fetch/process items. (Refactor the poll-cycle body into a testable unit.)
- **API stays light:** the FastAPI app starts without creating a queue-worker
  task (the freeze source is gone).
- **Handlers unchanged:** existing `queue_processor` / extraction / embedding
  tests continue to pass.
- **Frontend:** component test that the idle timer fires the prompt after the
  threshold and that Start calls resume; manual verification of the toggle.

## Out of Scope / Follow-ups

- Cross-process live SSE progress bridge.
- `sqlite-vec` indexed vector search.
- Auto-resume (vs. prompt) on idle, as an optional setting.
- Moving `busy_timeout`/pragma tuning (already adequate).

## Files Touched (anticipated)

- **New:** `backend/grimoire/worker/run.py`
- `backend/grimoire/main.py` — remove in-app worker from lifespan
- `backend/grimoire/services/queue_processor.py` — DB-backed pause; poll-cycle
  pause check; startup force-pause helper
- `backend/grimoire/worker/tasks.py` — strip queue-processing overlap
- `backend/grimoire/api/routes/queue.py` — remove inline processing endpoints
- `start.bat`, `start.sh` — launch the dedicated worker
- **Frontend:** "I'm working" toggle, `/queue/stats` polling, idle-prompt component
