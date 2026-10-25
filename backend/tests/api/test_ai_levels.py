"""Level 0 is a real level (a DCC funnel) and survives every identification write.

The writes used `if data.get("level_range_min"):`, which drops 0. Product types
coming back from a model pass through the vocab onto the Codex enum.
"""
import json

import pytest
from httpx import ASGITransport, AsyncClient

import grimoire.processors.ai_identifier as ai_identifier
from grimoire.database import get_db
from grimoire.main import app
from grimoire.models.product import Product
from grimoire.services.queue_processor import handle_ai_identify_task


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


async def _product(db, **kw):
    p = Product(file_path="/t/f.pdf", file_name="f.pdf", file_size=1, file_hash="f1",
                level_range_min=3, level_range_max=5, **kw)
    db.add(p)
    await db.commit()
    return p


@pytest.mark.asyncio
async def test_identify_apply_stores_level_zero(client, db):
    p = await _product(db)

    response = await client.post(f"/api/v1/ai/identify/{p.id}/confirm",
                                 json={"level_range_min": 0, "level_range_max": 0,
                                       "product_type": "Adventure"})

    assert response.status_code == 200
    await db.refresh(p)
    assert (p.level_range_min, p.level_range_max) == (0, 0)
    assert p.product_type == "adventure"


@pytest.mark.asyncio
async def test_worker_identify_stores_level_zero_and_enum_type(db, tmp_path, monkeypatch):
    text_file = tmp_path / "t.json"
    text_file.write_text(json.dumps({"markdown": "A funnel for 0-level characters. " * 10}),
                         encoding="utf-8")
    p = await _product(db, text_extracted=True, extracted_text_path=str(text_file))

    async def fake_identify(text, provider=None, filename=None):
        return {"product_type": "Core Rulebook", "level_range_min": 0, "level_range_max": 0}

    monkeypatch.setattr(ai_identifier, "identify_product", fake_identify)

    assert await handle_ai_identify_task(db, p, {"provider": "ollama"})

    await db.refresh(p)
    assert (p.level_range_min, p.level_range_max) == (0, 0)
    assert p.product_type == "core_rulebook"
