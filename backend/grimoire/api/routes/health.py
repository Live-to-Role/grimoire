"""Health check endpoints."""

import os
import platform
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import APIRouter
from sqlalchemy import func, select, text

from grimoire import __version__
from grimoire.api.deps import DbSession
from grimoire.config import Settings, settings
from grimoire.models import ProcessingQueue, Product, Setting, WatchedFolder
from grimoire.utils.runtime import in_container

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
    for field_name in Settings.model_fields:
        if any(p in field_name.lower() for p in _SECRET_PATTERNS):
            val = getattr(settings, field_name, "")
            safe[f"{field_name}_set"] = bool(val)
        else:
            val = getattr(settings, field_name, None)
            if hasattr(val, "__fspath__"):
                val = str(val)
            elif isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            safe[field_name] = val
    return safe


def _system_info() -> dict:
    """Host facts that shape processing speed — cores, RAM, disk, GPU hints."""
    info = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "in_container": in_container(),
    }

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        info["total_memory_mb"] = round(os.sysconf("SC_PHYS_PAGES") * page_size / 1024 / 1024)
    except (ValueError, OSError, AttributeError):
        info["total_memory_mb"] = None

    try:
        usage = shutil.disk_usage(str(settings.data_dir))
        info["data_disk_free_mb"] = round(usage.free / 1024 / 1024)
    except OSError:
        info["data_disk_free_mb"] = None

    return info


async def _read_setting(db, key: str) -> str | None:
    """Read a raw settings-table value through the caller's session."""
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else None


async def _worker_info(db) -> dict:
    """Whether the queue-worker process is alive, and whether it is paused.

    "38 pending, nothing running" has two causes that look identical from the
    queue counts alone: the worker is paused, or the worker process was never
    started. The heartbeat is what tells them apart.
    """
    from grimoire.services.queue_processor import (
        PROCESSING_PAUSED_KEY,
        WORKER_HEARTBEAT_KEY,
        WORKER_HEARTBEAT_STALE_SECONDS,
        parse_heartbeat,
        parse_paused,
    )

    heartbeat = parse_heartbeat(await _read_setting(db, WORKER_HEARTBEAT_KEY))
    paused = parse_paused(await _read_setting(db, PROCESSING_PAUSED_KEY))

    age = None
    if heartbeat is not None:
        age = (datetime.now(UTC) - heartbeat).total_seconds()

    return {
        "heartbeat": heartbeat.isoformat() if heartbeat else None,
        "seconds_since_heartbeat": age,
        "running": age is not None and age < WORKER_HEARTBEAT_STALE_SECONDS,
        "stale_after_seconds": WORKER_HEARTBEAT_STALE_SECONDS,
        "paused": paused,
    }


async def _ollama_status(base_url: str) -> tuple[bool, list[str]]:
    """Ask Ollama for its model list. Returns (reachable, model names)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
        return True, [m.get("name", "") for m in models if m.get("name")]
    except Exception:
        return False, []


async def _ai_info(db, check_network: bool) -> dict:
    """AI provider wiring, with keys reported only as present/absent."""
    from grimoire.processors.ai_identifier import get_ollama_url

    base_url = await get_ollama_url()

    reachable: bool | None = None
    models: list[str] = []
    if check_network:
        reachable, models = await _ollama_status(base_url)

    async def _key_set(env_name: str, setting_key: str) -> bool:
        if os.getenv(env_name):
            return True
        return bool(await _read_setting(db, setting_key))

    return {
        "ollama_base_url": base_url,
        "ollama_reachable": reachable,
        "ollama_models": models,
        "openai_key_set": await _key_set("OPENAI_API_KEY", "openai_api_key"),
        "anthropic_key_set": await _key_set("ANTHROPIC_API_KEY", "anthropic_api_key"),
    }


async def _library_info(db) -> dict:
    """Watched folders as the *server* sees them, not as the user typed them.

    In Docker these are container paths; a folder the container cannot see is
    the single most common reason a scan finds nothing.
    """
    result = await db.execute(select(WatchedFolder).order_by(WatchedFolder.path))
    folders = result.scalars().all()

    entries = []
    for folder in folders:
        path = Path(folder.path)
        exists = path.is_dir()
        readable = exists and os.access(path, os.R_OK | os.X_OK)

        count_result = await db.execute(
            select(func.count()).where(Product.watched_folder_id == folder.id)
        )
        entries.append(
            {
                "path": folder.path,
                "label": folder.label,
                "enabled": folder.enabled,
                "exists": exists,
                "readable": readable,
                "product_count": count_result.scalar() or 0,
                "last_scanned_at": folder.last_scanned_at.isoformat()
                if folder.last_scanned_at
                else None,
            }
        )

    return {"watched_folders": entries}


def _find_problems(worker: dict, queue: dict, library: dict, ai: dict) -> list[dict]:
    """Turn the raw numbers into the sentences a support reply would write."""
    problems: list[dict] = []
    pending = queue["pending"]

    if pending and not worker["running"]:
        problems.append(
            {
                "severity": "error",
                "code": "queue_worker_not_running",
                "message": (
                    f"{pending} items are queued but the background worker is not running "
                    "(no recent heartbeat). Queued work will never start."
                ),
                "hint": (
                    "Docker: check that the 'queue-worker' service is up "
                    "(`docker compose ps`). Native: check that "
                    "`python -m grimoire.worker.run` is running."
                ),
            }
        )
    elif pending and worker["paused"]:
        problems.append(
            {
                "severity": "info",
                "code": "processing_paused",
                "message": (
                    f"{pending} items are queued and Grimoire is paused, so nothing is "
                    "being processed."
                ),
                "hint": "Flip the status widget to 'Grimoire Working' to start processing.",
            }
        )

    if queue["stuck_processing"] and not worker["running"]:
        problems.append(
            {
                "severity": "warning",
                "code": "stuck_processing_items",
                "message": (
                    f"{queue['stuck_processing']} items are stuck in 'processing' with no "
                    "worker running. They will be reset when the worker next starts."
                ),
                "hint": "Start the worker, or use Maintenance → Reset stuck queue items.",
            }
        )

    if queue["failed"]:
        problems.append(
            {
                "severity": "warning",
                "code": "failed_queue_items",
                "message": f"{queue['failed']} queue items have failed.",
                "hint": "See queue.recent_errors below for the messages.",
            }
        )

    folders = library["watched_folders"]
    if not folders:
        problems.append(
            {
                "severity": "warning",
                "code": "no_library_folders",
                "message": "No library folders are configured, so no PDFs can be found.",
                "hint": (
                    "Settings → Library Folders. In Docker add the container paths "
                    "(/library, /library2, /library3), not the host paths."
                ),
            }
        )
    for folder in folders:
        if not folder["exists"]:
            problems.append(
                {
                    "severity": "error",
                    "code": "library_folder_missing",
                    "message": f"Library folder {folder['path']} does not exist on the server.",
                    "hint": (
                        "In Docker the path must be the container path (/library, /library2, "
                        "/library3) and PDF_LIBRARY_PATH must be set in .env before first start."
                    ),
                }
            )
        elif not folder["readable"]:
            problems.append(
                {
                    "severity": "error",
                    "code": "library_folder_unreadable",
                    "message": f"Library folder {folder['path']} exists but is not readable.",
                    "hint": "Check the permissions on the host folder that is mounted there.",
                }
            )

    if ai["ollama_reachable"] is False and not (
        ai["openai_key_set"] or ai["anthropic_key_set"]
    ):
        problems.append(
            {
                "severity": "warning",
                "code": "no_ai_provider",
                "message": (
                    f"Ollama is not reachable at {ai['ollama_base_url']} and no cloud API key "
                    "is configured, so AI identification cannot run."
                ),
                "hint": (
                    "Docker on Windows/macOS: http://host.docker.internal:11434. "
                    "Docker on Linux: http://172.17.0.1:11434. Confirm with `ollama list`."
                ),
            }
        )

    return problems


async def get_diagnostics_data(db, check_network: bool = True) -> dict:
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

    # Pending work broken down by task type
    pending_type_result = await db.execute(
        select(ProcessingQueue.task_type, func.count(ProcessingQueue.id))
        .where(ProcessingQueue.status == "pending")
        .group_by(ProcessingQueue.task_type)
    )
    pending_by_type = dict(pending_type_result.all())

    # Age of the oldest pending item — a queue that is moving has a young head
    oldest_pending_result = await db.execute(
        select(func.min(ProcessingQueue.created_at)).where(
            ProcessingQueue.status == "pending"
        )
    )
    oldest_pending = oldest_pending_result.scalar()
    oldest_pending_age = None
    if oldest_pending is not None:
        if oldest_pending.tzinfo is None:
            oldest_pending = oldest_pending.replace(tzinfo=UTC)
        oldest_pending_age = (datetime.now(UTC) - oldest_pending).total_seconds()

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

    # Stuck items
    stuck_result = await db.execute(
        select(func.count(ProcessingQueue.id))
        .where(ProcessingQueue.status == "processing")
    )
    stuck_count = stuck_result.scalar() or 0

    queue = {
        "pending": queue_by_status.get("pending", 0),
        "processing": queue_by_status.get("processing", 0),
        "completed": queue_by_status.get("completed", 0),
        "failed": queue_by_status.get("failed", 0),
        "pending_by_type": pending_by_type,
        "oldest_pending_age_seconds": oldest_pending_age,
        "stuck_processing": stuck_count,
        "recent_errors": recent_errors,
    }

    worker = await _worker_info(db)
    library = await _library_info(db)
    ai = await _ai_info(db, check_network)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "app": {
            "version": __version__,
        },
        "system": _system_info(),
        "config": _safe_config(),
        "database": {
            "product_count": product_count,
        },
        "worker": worker,
        "queue": queue,
        "library": library,
        "ai": ai,
        "problems": _find_problems(worker, queue, library, ai),
    }


@router.get("/health/diagnostics")
async def diagnostics(db: DbSession) -> dict:
    """Comprehensive diagnostics for bug reports.

    Returns system info, config (secrets redacted), database stats, queue
    health, worker liveness and a plain-language list of detected problems.
    Users can copy-paste this output for bug reports.
    """
    return await get_diagnostics_data(db)
