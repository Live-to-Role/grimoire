"""Health check endpoints."""

import platform
import sys

from fastapi import APIRouter
from sqlalchemy import func, select, text

from grimoire import __version__
from grimoire.api.deps import DbSession
from grimoire.config import Settings, settings
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

    # Stuck items
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
