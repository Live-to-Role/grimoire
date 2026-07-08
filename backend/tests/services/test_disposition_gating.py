"""ai_identify / embed re-queue and the disposition predicate respect the flags."""
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy import select

from grimoire.models.product import Product
from grimoire.models import ProcessingQueue
from grimoire.services.queue_processor import (
    queue_ai_identify_if_enabled,
    _auto_requeue_embeddings,
    is_processing_disposition_blocked,
)


async def _count(db, product_id, task_type):
    res = await db.execute(
        select(ProcessingQueue).where(
            ProcessingQueue.product_id == product_id,
            ProcessingQueue.task_type == task_type,
        )
    )
    return len(list(res.scalars().all()))


def _mk(**kw):
    base = dict(file_size=1)
    base.update(kw)
    return Product(**base)


def test_disposition_predicate():
    assert is_processing_disposition_blocked(_mk(file_path="/a", file_name="a", file_hash="a")) is False
    assert is_processing_disposition_blocked(
        _mk(file_path="/b", file_name="b", file_hash="b", is_image_content=True)) is True
    assert is_processing_disposition_blocked(
        _mk(file_path="/c", file_name="c", file_hash="c", text_unextractable=True)) is True


def _settings_stub(db, key, default=None):
    # Force auto-identify ON with the OpenAI provider (no network needed).
    return {"auto_identify_on_scan": True, "auto_identify_provider": "openai"}.get(key, default)


@pytest.mark.asyncio
async def test_ai_identify_gated_by_disposition(db, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    normal = _mk(file_path="/t/ai_ok.pdf", file_name="ai_ok.pdf", file_hash="aiok", text_extracted=True)
    image = _mk(file_path="/t/ai_i.pdf", file_name="ai_i.pdf", file_hash="aii", text_extracted=True, is_image_content=True)
    dead = _mk(file_path="/t/ai_d.pdf", file_name="ai_d.pdf", file_hash="aid", text_extracted=True, text_unextractable=True)
    notext = _mk(file_path="/t/ai_n.pdf", file_name="ai_n.pdf", file_hash="ain", text_extracted=False)
    db.add_all([normal, image, dead, notext])
    await db.commit()

    with patch("grimoire.services.queue_processor.get_setting", new=AsyncMock(side_effect=_settings_stub)):
        for p in (normal, image, dead, notext):
            await queue_ai_identify_if_enabled(db, p)
    await db.commit()

    assert await _count(db, normal.id, "ai_identify") == 1   # positive control
    assert await _count(db, image.id, "ai_identify") == 0
    assert await _count(db, dead.id, "ai_identify") == 0
    assert await _count(db, notext.id, "ai_identify") == 0


@pytest.mark.asyncio
async def test_auto_requeue_embeddings_skips_unextractable(db):
    normal = _mk(file_path="/t/e_ok.pdf", file_name="e_ok.pdf", file_hash="eok",
                 text_extracted=True, extracted_text_path="/t/e_ok.json")
    dead = _mk(file_path="/t/e_d.pdf", file_name="e_d.pdf", file_hash="edd",
               text_extracted=True, text_unextractable=True, extracted_text_path="/t/e_d.json")
    db.add_all([normal, dead])
    await db.commit()

    # Make a provider "available" deterministically (local model) without network.
    with patch("grimoire.services.embeddings.SENTENCE_TRANSFORMERS_AVAILABLE", True), \
         patch("grimoire.processors.ai_identifier.check_ollama_available", return_value=False), \
         patch("grimoire.processors.ai_identifier.get_ollama_url", new=AsyncMock(return_value=None)), \
         patch("grimoire.processors.ai_identifier.get_setting_from_db", new=AsyncMock(return_value="")):
        await _auto_requeue_embeddings(db)
    await db.commit()

    assert await _count(db, normal.id, "embed") == 1   # positive control
    assert await _count(db, dead.id, "embed") == 0
