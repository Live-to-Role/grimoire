# Logging & Diagnostics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve debugging experience by centralizing backend logging, adding a diagnostics endpoint, and surfacing processing errors in the UI.

**Architecture:** Three independent improvements: (1) centralized Python logging with file rotation, (2) a `/health/diagnostics` endpoint returning system/queue/config info, (3) inline error display in ProcessingQueue and ProductDetail components.

**Tech Stack:** Python logging (stdlib), FastAPI, React/TypeScript, TailwindCSS

---

### Task 1: Centralized Logging Setup

**Files:**
- Create: `backend/grimoire/logging_config.py`
- Modify: `backend/grimoire/config.py`
- Modify: `backend/grimoire/main.py`
- Test: `backend/tests/test_logging_config.py`

**Step 1: Write the failing test**

Create `backend/tests/test_logging_config.py`:

```python
"""Tests for centralized logging configuration."""

import logging
from pathlib import Path
from unittest.mock import patch

from grimoire.logging_config import setup_logging


def test_setup_logging_configures_root_level():
    """Root logger level should match the configured level."""
    with patch("grimoire.logging_config.settings") as mock_settings:
        mock_settings.log_level = "WARNING"
        mock_settings.log_file = ""
        setup_logging()
        assert logging.getLogger().level == logging.WARNING


def test_setup_logging_default_info():
    """Default log level should be INFO."""
    with patch("grimoire.logging_config.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_file = ""
        setup_logging()
        assert logging.getLogger().level == logging.INFO


def test_setup_logging_console_format():
    """Console handler should use structured format."""
    with patch("grimoire.logging_config.settings") as mock_settings:
        mock_settings.log_level = "INFO"
        mock_settings.log_file = ""
        setup_logging()
        root = logging.getLogger()
        # Should have at least a console handler
        stream_handlers = [
            h for h in root.handlers if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(stream_handlers) >= 1


def test_setup_logging_file_handler(tmp_path):
    """File handler should be added when log_file is configured."""
    log_file = tmp_path / "test.log"
    with patch("grimoire.logging_config.settings") as mock_settings:
        mock_settings.log_level = "DEBUG"
        mock_settings.log_file = str(log_file)
        setup_logging()
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) >= 1

    # Clean up handlers to avoid affecting other tests
    for h in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(h)


def test_setup_logging_suppresses_noisy_loggers():
    """Third-party loggers should be set to WARNING."""
    with patch("grimoire.logging_config.settings") as mock_settings:
        mock_settings.log_level = "DEBUG"
        mock_settings.log_file = ""
        setup_logging()
        assert logging.getLogger("uvicorn.access").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_logging_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'grimoire.logging_config'`

**Step 3: Add `log_file` setting to config**

In `backend/grimoire/config.py`, add after `log_level`:

```python
    log_file: str = ""  # Path to log file, empty = no file logging
```

**Step 4: Create `logging_config.py`**

Create `backend/grimoire/logging_config.py`:

```python
"""Centralized logging configuration."""

import logging
import logging.handlers

from grimoire.config import settings

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Noisy third-party loggers to suppress
NOISY_LOGGERS = [
    "uvicorn.access",
    "httpcore",
    "httpx",
    "aiosqlite",
    "sqlalchemy.engine",
]


def setup_logging() -> None:
    """Configure logging for the application.

    Sets up console handler (always) and optional rotating file handler.
    Suppresses noisy third-party loggers.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()

    # Clear existing handlers to avoid duplicates on re-init
    root.handlers.clear()
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # File handler (optional)
    if settings.log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            settings.log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Suppress noisy loggers
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
```

**Step 5: Wire up in main.py**

In `backend/grimoire/main.py`, add at the top of the `lifespan` function (before `await init_db()`):

```python
    from grimoire.logging_config import setup_logging
    setup_logging()
```

**Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_logging_config.py -v`
Expected: All 5 tests PASS

**Step 7: Run full test suite for regressions**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 8: Commit**

```bash
git add backend/grimoire/logging_config.py backend/grimoire/config.py backend/grimoire/main.py backend/tests/test_logging_config.py
git commit -m "feat: add centralized logging with file rotation support"
```

---

### Task 2: Diagnostics Endpoint

**Files:**
- Modify: `backend/grimoire/api/routes/health.py`
- Test: `backend/tests/api/test_diagnostics.py`

**Step 1: Write the failing test**

Create `backend/tests/api/test_diagnostics.py`:

```python
"""Tests for the diagnostics endpoint."""

import platform
import sys

import pytest
from sqlalchemy import select

from grimoire import __version__
from grimoire.api.routes.health import get_diagnostics_data
from grimoire.models import ProcessingQueue, Product


@pytest.fixture
async def sample_data(db):
    """Create sample products and queue items for diagnostics."""
    product = Product(file_name="test.pdf", file_path="/test/test.pdf", file_size=1024)
    db.add(product)
    await db.flush()

    # One completed, one failed queue item
    db.add(ProcessingQueue(
        product_id=product.id, task_type="text", status="completed",
    ))
    db.add(ProcessingQueue(
        product_id=product.id, task_type="ai_identify", status="failed",
        error_message="Provider not configured",
    ))
    db.add(ProcessingQueue(
        product_id=product.id, task_type="cover", status="pending",
    ))
    await db.flush()
    return product


async def test_diagnostics_returns_version(db):
    """Diagnostics should include app version."""
    data = await get_diagnostics_data(db)
    assert data["app"]["version"] == __version__


async def test_diagnostics_returns_python_info(db):
    """Diagnostics should include Python version and platform."""
    data = await get_diagnostics_data(db)
    assert data["system"]["python_version"] == sys.version
    assert "platform" in data["system"]


async def test_diagnostics_returns_queue_stats(db, sample_data):
    """Diagnostics should include queue item counts by status."""
    data = await get_diagnostics_data(db)
    assert data["queue"]["completed"] == 1
    assert data["queue"]["failed"] == 1
    assert data["queue"]["pending"] == 1


async def test_diagnostics_returns_recent_errors(db, sample_data):
    """Diagnostics should include recent error messages."""
    data = await get_diagnostics_data(db)
    errors = data["queue"]["recent_errors"]
    assert len(errors) == 1
    assert errors[0]["error_message"] == "Provider not configured"
    assert errors[0]["task_type"] == "ai_identify"


async def test_diagnostics_excludes_secrets(db):
    """Diagnostics must never include API keys or secrets."""
    data = await get_diagnostics_data(db)
    config = data["config"]
    for key in config:
        assert "key" not in key.lower() or key == "codex_api_key_set"
        assert "secret" not in key.lower()
        assert "password" not in key.lower()


async def test_diagnostics_returns_product_count(db, sample_data):
    """Diagnostics should include total product count."""
    data = await get_diagnostics_data(db)
    assert data["database"]["product_count"] == 1
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/test_diagnostics.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_diagnostics_data'`

**Step 3: Implement the diagnostics endpoint**

Add to `backend/grimoire/api/routes/health.py`:

```python
"""Health check endpoints."""

import platform
import sys
from datetime import datetime, UTC

from fastapi import APIRouter
from sqlalchemy import func, select, text

from grimoire import __version__
from grimoire.api.deps import DbSession
from grimoire.config import settings
from grimoire.models import ProcessingQueue, Product

router = APIRouter()


@router.get("/health")
async def health_check(db: DbSession) -> dict:
    """Basic health check endpoint."""
    db_healthy = False
    try:
        await db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception:
        pass

    return {
        "status": "healthy" if db_healthy else "degraded",
        "database": "connected" if db_healthy else "disconnected",
        "version": __version__,
    }


@router.get("/health/ready")
async def readiness_check(db: DbSession) -> dict:
    """Readiness check for load balancers."""
    checks = {
        "database": False,
    }

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass

    all_ready = all(checks.values())
    return {
        "ready": all_ready,
        "checks": checks,
    }


# Keys that must never appear in diagnostics output
_SECRET_PATTERNS = {"key", "secret", "password", "token"}


def _safe_config() -> dict:
    """Return config values with secrets redacted."""
    safe = {}
    for field_name in settings.model_fields:
        if any(p in field_name.lower() for p in _SECRET_PATTERNS):
            # Only report whether the secret is set, not its value
            val = getattr(settings, field_name, "")
            safe[f"{field_name}_set"] = bool(val)
        else:
            val = getattr(settings, field_name, None)
            # Convert Path objects to strings
            if hasattr(val, "__fspath__"):
                val = str(val)
            # Convert lists to strings
            elif isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            safe[field_name] = val
    return safe


async def get_diagnostics_data(db) -> dict:
    """Gather diagnostic data. Extracted for testability."""
    # Product count
    product_count_result = await db.execute(select(func.count(Product.id)))
    product_count = product_count_result.scalar() or 0

    # Queue stats by status
    queue_stats_result = await db.execute(
        select(ProcessingQueue.status, func.count(ProcessingQueue.id))
        .group_by(ProcessingQueue.status)
    )
    queue_by_status = dict(queue_stats_result.all())

    # Recent errors (last 10)
    recent_errors_result = await db.execute(
        select(
            ProcessingQueue.task_type,
            ProcessingQueue.error_message,
            ProcessingQueue.completed_at,
            ProcessingQueue.product_id,
        )
        .where(
            ProcessingQueue.status == "failed",
            ProcessingQueue.error_message.isnot(None),
        )
        .order_by(ProcessingQueue.completed_at.desc())
        .limit(10)
    )
    recent_errors = [
        {
            "task_type": row.task_type,
            "error_message": row.error_message,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "product_id": row.product_id,
        }
        for row in recent_errors_result.all()
    ]

    # Stuck items (processing for too long — no timeout, just count them)
    stuck_result = await db.execute(
        select(func.count(ProcessingQueue.id))
        .where(ProcessingQueue.status == "processing")
    )
    stuck_count = stuck_result.scalar() or 0

    return {
        "app": {
            "version": __version__,
        },
        "system": {
            "python_version": sys.version,
            "platform": platform.platform(),
        },
        "config": _safe_config(),
        "database": {
            "product_count": product_count,
        },
        "queue": {
            "pending": queue_by_status.get("pending", 0),
            "processing": queue_by_status.get("processing", 0),
            "completed": queue_by_status.get("completed", 0),
            "failed": queue_by_status.get("failed", 0),
            "stuck_processing": stuck_count,
            "recent_errors": recent_errors,
        },
    }


@router.get("/health/diagnostics")
async def diagnostics(db: DbSession) -> dict:
    """Comprehensive diagnostics for bug reports.

    Returns system info, config (secrets redacted), database stats,
    and queue health. Users can copy-paste this output for bug reports.
    """
    return await get_diagnostics_data(db)
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/api/test_diagnostics.py -v`
Expected: All 6 tests PASS

**Step 5: Run full test suite for regressions**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add backend/grimoire/api/routes/health.py backend/tests/api/test_diagnostics.py
git commit -m "feat: add /health/diagnostics endpoint for bug reports"
```

---

### Task 3: Surface Errors in ProcessingQueue Component

**Files:**
- Modify: `frontend/src/components/ProcessingQueue.tsx`

**Step 1: Replace the tooltip-only error display with inline expandable errors**

In `frontend/src/components/ProcessingQueue.tsx`, find the error display section (around lines 329-336):

```tsx
{item.error_message && (
  <span
    className="ml-2 text-xs text-red-500 cursor-help"
    title={item.error_message}
  >
    Error
  </span>
)}
```

Replace with:

```tsx
{item.error_message && (
  <button
    onClick={() => setExpandedError(expandedError === item.id ? null : item.id)}
    className="ml-2 text-xs text-red-500 hover:text-red-700 underline"
  >
    {expandedError === item.id ? 'Hide Error' : 'Show Error'}
  </button>
)}
```

**Step 2: Add the expandable error row below each queue item row**

After the closing `</tr>` of each queue item (line 339), add:

```tsx
{expandedError === item.id && item.error_message && (
  <tr>
    <td colSpan={4} className="px-4 py-2 bg-red-50 border-b border-red-100">
      <div className="flex items-start justify-between gap-2">
        <pre className="text-xs text-red-700 whitespace-pre-wrap font-mono flex-1">
          {item.error_message}
        </pre>
        <button
          onClick={() => {
            navigator.clipboard.writeText(item.error_message || '');
          }}
          className="shrink-0 rounded px-2 py-1 text-xs text-red-600 hover:bg-red-100"
          title="Copy error"
        >
          Copy
        </button>
      </div>
    </td>
  </tr>
)}
```

**Step 3: Add the `expandedError` state**

Near the top of the component, add:

```tsx
const [expandedError, setExpandedError] = useState<number | null>(null);
```

**Step 4: Manually test in browser**

1. Start the app: `cd backend && uvicorn grimoire.main:app --reload` and `cd frontend && npm run dev`
2. Navigate to the Processing Queue
3. If there are failed items, verify "Show Error" link appears and clicking it expands the error message inline
4. Verify "Copy" button copies the error text to clipboard

**Step 5: Commit**

```bash
git add frontend/src/components/ProcessingQueue.tsx
git commit -m "feat: show inline expandable errors in processing queue"
```

---

### Task 4: Surface Errors in ProductDetail Component

**Files:**
- Modify: `frontend/src/components/ProductDetail.tsx`
- May modify: `frontend/src/api/` (if queue query by product needed)

**Step 1: Add a query for failed queue items for the current product**

In `frontend/src/components/ProductDetail.tsx`, add a React Query hook near the other queries in the component:

```tsx
const { data: failedQueueItems } = useQuery({
  queryKey: ['queue-errors', product.id],
  queryFn: async () => {
    const response = await apiClient.get('/queue/items', {
      params: { status: 'failed', limit: 10 },
    });
    // Filter to this product's items client-side
    return (response.data.items || []).filter(
      (item: any) => item.product_id === product.id
    );
  },
});
```

**Step 2: Add error banner in the Processing Status Bar**

In the Processing Status Bar section (around line 1475), after the status dots and before the flex spacer, add:

```tsx
{failedQueueItems && failedQueueItems.length > 0 && (
  <div className="flex items-center gap-2">
    <span className="h-2 w-2 rounded-full bg-red-500" />
    <span className="text-sm text-red-600">
      {failedQueueItems.length} failed task{failedQueueItems.length > 1 ? 's' : ''}
    </span>
  </div>
)}
```

**Step 3: Add expandable error details below the status bar**

After the Processing Status Bar `</div>` (around line 1485), add:

```tsx
{failedQueueItems && failedQueueItems.length > 0 && (
  <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3">
    <p className="text-sm font-medium text-red-800 mb-2">Processing Errors</p>
    {failedQueueItems.map((item: any) => (
      <div key={item.id} className="flex items-start justify-between gap-2 mb-1 last:mb-0">
        <div className="flex-1">
          <span className="text-xs font-medium text-red-700">{item.task_type}:</span>
          <span className="ml-1 text-xs text-red-600">{item.error_message}</span>
        </div>
        <button
          onClick={() => navigator.clipboard.writeText(item.error_message || '')}
          className="shrink-0 text-xs text-red-500 hover:text-red-700 underline"
        >
          Copy
        </button>
      </div>
    ))}
  </div>
)}
```

**Step 4: Manually test in browser**

1. Open a product that has failed queue items
2. Verify the red dot and "N failed tasks" text appears in the status bar
3. Verify the error details panel shows below with task type and error message
4. Verify Copy button works

**Step 5: Commit**

```bash
git add frontend/src/components/ProductDetail.tsx
git commit -m "feat: show processing errors in product detail view"
```

---

### Task 5: Final Integration Test

**Step 1: Run full backend test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Verify diagnostics endpoint manually**

Run: `curl http://localhost:8000/api/v1/health/diagnostics | python -m json.tool`

Verify:
- Version is present
- No API keys or secrets appear in output
- Queue stats show correct counts
- Recent errors list is populated (if any failed items exist)

**Step 3: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: address integration issues"
```
