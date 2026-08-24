# Logging & Diagnostics Improvements

**Date:** 2026-03-08
**Status:** Approved

## Problem

When users encounter bugs, there's no easy way to gather useful diagnostic information. Logging is ad-hoc (bare `logging.getLogger(__name__)` with no centralized format), the health endpoint returns minimal info, and processing errors are barely visible in the UI (tooltip-only in queue, invisible in ProductDetail).

## Scope

Three focused improvements, ordered by value:

### 1. Structured Backend Logging

**Current state:** Each module calls `logging.getLogger(__name__)` independently. No centralized configuration, no consistent format, no log level setup in `main.py`.

**Changes:**
- Add a `logging_config.py` module that configures Python logging centrally at startup
- Structured log format with timestamp, level, module, and message: `[2026-03-08 14:23:01] [INFO] [queue_processor] Processing batch of 5 items`
- Configure log level from `settings.log_level` (already exists in config)
- Call the setup function from `main.py` lifespan before anything else
- Add a rotating file handler so logs persist to `data/grimoire.log` (configurable path, max 10MB, 3 backups)
- Keep console handler for Docker/terminal use

**Files to modify:**
- New: `backend/grimoire/logging_config.py`
- Edit: `backend/grimoire/main.py` (call setup in lifespan)
- Edit: `backend/grimoire/config.py` (add `log_file` setting)

### 2. Diagnostics Endpoint

**Current state:** `/api/v1/health` returns only DB status and version.

**Changes:**
- Add `GET /api/v1/health/diagnostics` endpoint that returns:
  - App version, Python version, platform info
  - Configuration (non-secret fields only — explicitly exclude API keys, secret_key)
  - Database stats: product count, queue item counts by status
  - Queue health: items stuck in "processing", recent failures (last 10 error messages with timestamps)
  - Disk space for data_dir and library_path
  - AI provider availability (configured vs. not, without exposing keys)
- Response is a single JSON blob a user can copy-paste into a bug report
- No authentication required (matches existing health endpoints), but secrets are never included

**Files to modify:**
- Edit: `backend/grimoire/api/routes/health.py`

### 3. Surface Errors in the UI

**Current state:** Queue errors show as a tiny red "Error" tooltip. ProductDetail doesn't show queue errors at all. SSE task_failed events are published but not consumed.

**Changes:**

**ProcessingQueue component:**
- Show error messages inline (expandable) instead of tooltip-only
- Failed items get a visible error row beneath the item showing the full error message
- Add a "Copy error" button for easy reporting

**ProductDetail component:**
- Show a warning banner when the product has failed queue items
- Display the error message and which task type failed (cover_extract, text_extract, ai_identify)
- Query queue items for the product to get error details (API already supports filtering by product_id)

**No new API endpoints needed** — the existing queue API already returns `error_message` and supports product_id filtering.

**Files to modify:**
- Edit: `frontend/src/components/ProcessingQueue.tsx`
- Edit: `frontend/src/components/ProductDetail.tsx`
- May need: `frontend/src/api/` for a queue items query by product_id if not already wired up

## Out of Scope

- Log viewer UI (technical users can read log files directly)
- Bug report packaging/submission
- Log shipping to external services
- Real-time SSE error consumption (nice-to-have for later)

## Dependencies

None. All three changes are independent of each other and can be done in any order.
