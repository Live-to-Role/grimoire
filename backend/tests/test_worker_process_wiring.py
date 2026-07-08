"""Guards for the worker-process wiring."""
import asyncio
import importlib


def test_worker_run_module_importable_and_has_main():
    mod = importlib.import_module("grimoire.worker.run")
    assert asyncio.iscoroutinefunction(mod.main)


def test_api_lifespan_does_not_start_queue_worker():
    import inspect
    from grimoire.main import lifespan

    src = inspect.getsource(lifespan)
    assert "run_queue_worker" not in src, "API lifespan must not run the queue worker"


def test_inline_queue_processing_endpoints_removed():
    from grimoire.main import app

    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/v1/queue/process" not in paths
    assert "/api/v1/queue/{item_id}/process" not in paths
