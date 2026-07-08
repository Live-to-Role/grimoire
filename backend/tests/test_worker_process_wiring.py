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
