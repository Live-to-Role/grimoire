"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from grimoire import __version__
from grimoire.api.routes import api_router
from grimoire.config import settings
from grimoire.database import init_db
from grimoire.middleware import RateLimitMiddleware, CacheMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    import asyncio
    
    await init_db()

    # Watcher disabled temporarily - causing startup hang with watched folders
    # from grimoire.services.watcher import start_watcher, stop_watcher
    # await start_watcher()
    
    # Start queue worker for PDF processing
    from grimoire.services.queue_processor import run_queue_worker
    queue_stop_event = asyncio.Event()
    queue_task = asyncio.create_task(
        run_queue_worker(poll_interval=5.0, batch_size=3, stop_event=queue_stop_event)
    )
    
    # Start contribution queue processor for Codex submissions
    from grimoire.services.contribution_queue_processor import (
        start_queue_processor,
        stop_queue_processor,
    )
    from grimoire.database import get_db_session
    await start_queue_processor(get_db_session)

    yield

    # Stop contribution queue processor
    stop_queue_processor()

    # Stop queue worker
    queue_stop_event.set()
    queue_task.cancel()
    try:
        await queue_task
    except asyncio.CancelledError:
        pass
    
    # Watcher disabled
    # await stop_watcher()


app = FastAPI(
    title="Grimoire",
    description="A self-hosted digital library manager for tabletop RPG content",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(CacheMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Grimoire",
        "version": __version__,
        "docs": "/api/docs",
    }
