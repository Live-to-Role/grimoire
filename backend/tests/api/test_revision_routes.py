import pytest
from httpx import AsyncClient, ASGITransport
from grimoire.models.product import Product
from grimoire.main import app
from grimoire.database import get_db


@pytest.fixture
def client(db):
    """Create test client with DB dependency override."""
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_revision_groups(client, db):
    """GET /api/v1/duplicates?type=revision returns revision candidates."""
    old = Product(
        file_path="/t/AR.pdf", file_name="AR.pdf", file_hash="aar",
        file_size=100, normalized_stem="ar", title="A",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/AR_v2.pdf", file_name="AR_v2.pdf", file_hash="bbr",
        file_size=200, normalized_stem="ar", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    async with client as c:
        resp = await c.get("/api/v1/duplicates", params={"type": "revision"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_confirm_revision_endpoint(client, db):
    """POST /api/v1/duplicates/{id}/confirm-revision supersedes the product."""
    old = Product(
        file_path="/t/AC.pdf", file_name="AC.pdf", file_hash="aac",
        file_size=100, normalized_stem="ac", title="A", author="Test Author",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/AC_v2.pdf", file_name="AC_v2.pdf", file_hash="bbc",
        file_size=200, normalized_stem="ac", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    async with client as c:
        resp = await c.post(f"/api/v1/duplicates/{old.id}/confirm-revision")
    assert resp.status_code == 200

    await db.refresh(old)
    assert old.is_superseded is True


@pytest.mark.asyncio
async def test_dismiss_revision_endpoint(client, db):
    """POST /api/v1/duplicates/{id}/dismiss-revision clears revision marking."""
    old = Product(
        file_path="/t/AD.pdf", file_name="AD.pdf", file_hash="aad",
        file_size=100, normalized_stem="ad", title="A",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/AD_v2.pdf", file_name="AD_v2.pdf", file_hash="bbd",
        file_size=200, normalized_stem="ad", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    async with client as c:
        resp = await c.post(f"/api/v1/duplicates/{old.id}/dismiss-revision")
    assert resp.status_code == 200

    await db.refresh(old)
    assert old.is_duplicate is False


@pytest.mark.asyncio
async def test_revision_stats(client, db):
    """GET /api/v1/duplicates/stats includes revision_candidates count."""
    old = Product(
        file_path="/t/AE.pdf", file_name="AE.pdf", file_hash="aae",
        file_size=100, normalized_stem="ae", title="A",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/AE_v2.pdf", file_name="AE_v2.pdf", file_hash="bbe",
        file_size=200, normalized_stem="ae", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    async with client as c:
        resp = await c.get("/api/v1/duplicates/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "revision_candidates" in data
    assert data["revision_candidates"] >= 1


@pytest.mark.asyncio
async def test_scan_revisions(client, db):
    """POST /api/v1/duplicates/scan with scan_type=all runs revision detection."""
    p1 = Product(
        file_path="/t/BookS.pdf", file_name="BookS.pdf", file_hash="aas",
        file_size=100, normalized_stem="books", title="Book",
    )
    p2 = Product(
        file_path="/t/BookS_Revised.pdf", file_name="BookS_Revised.pdf", file_hash="bbs",
        file_size=200, normalized_stem="books", title="Book Revised",
    )
    db.add_all([p1, p2])
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/duplicates/scan", params={"scan_type": "all"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_superseded_products_hidden_from_list(client, db):
    """GET /api/v1/products excludes superseded products."""
    visible = Product(
        file_path="/t/Visible.pdf", file_name="Visible.pdf", file_hash="aav",
        file_size=100, normalized_stem="visible", title="Visible",
    )
    hidden = Product(
        file_path="/t/Hidden.pdf", file_name="Hidden.pdf", file_hash="bbv",
        file_size=200, normalized_stem="hidden", title="Hidden",
        is_superseded=True,
    )
    db.add_all([visible, hidden])
    await db.commit()

    async with client as c:
        # Check visible product appears
        resp = await c.get("/api/v1/products", params={"search": "Visible", "limit": 100})
        assert resp.status_code == 200
        data = resp.json()
        titles = [p["title"] for p in data["items"] if p.get("title")]
        assert "Visible" in titles

        # Check superseded product is hidden
        resp = await c.get("/api/v1/products", params={"search": "Hidden", "limit": 100})
        assert resp.status_code == 200
        data = resp.json()
        titles = [p["title"] for p in data["items"] if p.get("title")]
        assert "Hidden" not in titles
