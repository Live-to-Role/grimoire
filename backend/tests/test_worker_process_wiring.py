"""Guards for the worker-process wiring."""
import asyncio
import importlib


def test_worker_run_module_importable_and_has_main():
    mod = importlib.import_module("grimoire.worker.run")
    assert asyncio.iscoroutinefunction(mod.main)
