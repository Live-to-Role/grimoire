"""Guards that the Docker stack runs the same processes as start.sh / start.bat.

The ProcessingQueue drain loop (``grimoire.worker.run``) is the only thing that
turns queued items into processed products. The Huey consumer only schedules
folder scans. A compose file that starts Huey but not the queue worker looks
healthy while every item sits at "pending" forever.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_DOCKER_DIR = Path(__file__).resolve().parents[2] / "docker"
COMPOSE_FILES = ["docker-compose.yml", "docker-compose.dev.yml"]

QUEUE_WORKER_CMD = "grimoire.worker.run"
HUEY_CONSUMER_CMD = "huey_consumer"


def _services(compose_name: str) -> dict:
    path = _DOCKER_DIR / compose_name
    assert path.exists(), f"missing compose file: {path}"
    return yaml.safe_load(path.read_text())["services"]


def _command_text(service: dict) -> str:
    command = service.get("command", "")
    if isinstance(command, list):
        return " ".join(command)
    return command


@pytest.mark.parametrize("compose_name", COMPOSE_FILES)
def test_compose_runs_the_queue_worker(compose_name):
    """Some service must run `python -m grimoire.worker.run`."""
    services = _services(compose_name)
    running = [name for name, svc in services.items() if QUEUE_WORKER_CMD in _command_text(svc)]
    assert running, (
        f"{compose_name} starts no queue worker — queued items would never be processed"
    )


@pytest.mark.parametrize("compose_name", COMPOSE_FILES)
def test_compose_runs_the_huey_consumer(compose_name):
    """Folder-scan scheduling still needs the Huey consumer."""
    services = _services(compose_name)
    running = [name for name, svc in services.items() if HUEY_CONSUMER_CMD in _command_text(svc)]
    assert running, f"{compose_name} starts no Huey consumer — periodic scans would never run"


@pytest.mark.parametrize("compose_name", COMPOSE_FILES)
def test_queue_worker_can_reach_the_library_and_database(compose_name):
    """The queue worker opens the PDFs, so it needs the same mounts as the API."""
    services = _services(compose_name)
    api_mounts = {v.split(":", 1)[1] for v in services["grimoire"]["volumes"]}
    for name, svc in services.items():
        if QUEUE_WORKER_CMD not in _command_text(svc):
            continue
        mounts = {v.split(":", 1)[1] for v in svc.get("volumes", [])}
        missing = {m for m in api_mounts if m.startswith("/library")} - mounts
        assert not missing, f"{compose_name}:{name} is missing library mounts: {missing}"
        assert any(m.startswith("/app/data") for m in mounts), (
            f"{compose_name}:{name} cannot reach the database volume"
        )
