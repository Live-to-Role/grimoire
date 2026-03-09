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
    product = Product(file_name="test.pdf", file_path="/test/test.pdf", file_size=1024, file_hash="abc123")
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
        assert "key" not in key.lower() or key.endswith("_set")
        assert "secret" not in key.lower() or key.endswith("_set")
        assert "password" not in key.lower()


async def test_diagnostics_returns_product_count(db, sample_data):
    """Diagnostics should include total product count."""
    data = await get_diagnostics_data(db)
    assert data["database"]["product_count"] == 1
