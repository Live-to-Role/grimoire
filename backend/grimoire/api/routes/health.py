"""Health check endpoints."""

from fastapi import APIRouter
from sqlalchemy import text

from grimoire import __version__
from grimoire.api.deps import DbSession

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
