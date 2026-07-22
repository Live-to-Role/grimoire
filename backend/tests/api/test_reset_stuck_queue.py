"""POST /library/maintenance/reset-stuck must compare against UTC.

`started_at` is written as `datetime.now(UTC)` (queue_processor). Comparing it
against a local-clock cutoff silently breaks the endpoint in every timezone
except UTC: west of UTC nothing is ever reset, east of UTC everything is —
including tasks that are actively running.

Both assertions below are needed to catch both directions.
"""
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient, ASGITransport

from grimoire.main import app
from grimoire.database import get_db
from grimoire.models.product import Product
from grimoire.models import ProcessingQueue


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reset_stuck_uses_utc_not_local_time(client, db):
    product = Product(
        file_path="/t/reset-stuck.pdf", file_name="reset-stuck.pdf",
        file_size=1, file_hash="rs1",
    )
    db.add(product)
    await db.commit()

    now = datetime.now(UTC)
    stale = ProcessingQueue(
        product_id=product.id, task_type="text", status="processing",
        started_at=now - timedelta(minutes=90),
    )
    fresh = ProcessingQueue(
        product_id=product.id, task_type="text", status="processing",
        started_at=now - timedelta(minutes=1),
    )
    db.add_all([stale, fresh])
    await db.commit()

    async with client as c:
        resp = await c.post(
            "/api/v1/library/maintenance/reset-stuck",
            params={"timeout_minutes": 30},
        )

    assert resp.status_code == 200
    assert resp.json()["reset"] >= 1

    await db.refresh(stale)
    await db.refresh(fresh)

    # West of UTC the buggy cutoff is hours too early and this stays "processing".
    assert stale.status == "pending", "90-min-old item should have been reset"
    # East of UTC the buggy cutoff is in the future and this gets clobbered.
    assert fresh.status == "processing", "1-min-old item must NOT be reset"


@pytest.mark.asyncio
async def test_reset_stuck_returns_to_pending_not_failed(client, db):
    """Interrupted work should be retried, not parked in the failed pile."""
    product = Product(
        file_path="/t/reset-stuck2.pdf", file_name="reset-stuck2.pdf",
        file_size=1, file_hash="rs2",
    )
    db.add(product)
    await db.commit()

    item = ProcessingQueue(
        product_id=product.id, task_type="text", status="processing",
        started_at=datetime.now(UTC) - timedelta(hours=3),
    )
    db.add(item)
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/library/maintenance/reset-stuck")

    assert resp.status_code == 200
    await db.refresh(item)
    assert item.status == "pending"
    assert item.status != "failed"


@pytest.mark.asyncio
async def test_mark_missing_writes_utc(client, db):
    """scanner.py writes missing_since as UTC — this route must agree, or the
    same column holds two clocks hours apart."""
    product = Product(
        file_path="/t/definitely-not-here.pdf", file_name="gone.pdf",
        file_size=1, file_hash="rs3",
    )
    db.add(product)
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/library/maintenance/mark-missing")

    assert resp.status_code == 200
    await db.refresh(product)
    assert product.is_missing is True

    # Column is naive; the value stored must be UTC, not local.
    utc_now = datetime.now(UTC).replace(tzinfo=None)
    drift = abs((product.missing_since - utc_now).total_seconds())
    assert drift < 300, (
        f"missing_since is {drift:.0f}s from UTC now — looks like a local clock"
    )
