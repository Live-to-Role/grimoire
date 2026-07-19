# backend/tests/test_monster_extract_handler.py
"""Tests for the monster_extract queue handler (LLM mocked)."""

import json

import pytest
from sqlalchemy import select

from grimoire.models import MonsterEntry, Product
from grimoire.services.queue_processor import TaskError, handle_monster_extract_task

DCC_PAGES = [{"page": 12, "markdown": (
    "## Orc\n\nRaiders of the wastes.\n\n"
    "Orc: Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; MV 30'; Act 1d20; "
    "SV Fort +1, Ref +0, Will -1; AL C.\n"
)}]


def fake_entry(name="Orc", page=12):
    return {
        "name": name, "page_number": page, "system_profile": "dcc",
        "raw_text": "raw", "ac": 13, "hd_dice": "1d8+1", "hd_value": 1.0,
        "hp_avg": 5.5,
        "attacks": json.dumps([{"name": "claw", "bonus": 1, "damage_dice": "1d4", "damage_avg": 2.5}]),
        "move": "30'", "special_abilities": json.dumps([]),
        "environments": json.dumps(["wilderness"]), "extraction_confidence": 0.9,
        "flags": json.dumps([]), "review_status": "pending",
    }


async def make_product(db, path):
    product = Product(file_path=path, file_name=path.rsplit("/", 1)[-1], file_size=1, file_hash=path)
    db.add(product)
    await db.flush()
    return product


async def test_handler_persists_pending_entries(db, monkeypatch):
    product = await make_product(db, "/t/handler-basic.pdf")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("grimoire.services.processor.get_extracted_pages", lambda p: DCC_PAGES)

    async def fake_normalize(candidate, profile, provider=None, model=None):
        return fake_entry()

    monkeypatch.setattr("grimoire.processors.monster_normalizer.normalize_candidate", fake_normalize)

    ok = await handle_monster_extract_task(db, product, config={"system_profile": "dcc"})
    assert ok is True
    result = await db.execute(select(MonsterEntry).where(MonsterEntry.product_id == product.id))
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].review_status == "pending"


async def test_handler_fails_without_pages(db, monkeypatch):
    product = await make_product(db, "/t/handler-nopages.pdf")
    monkeypatch.setattr("grimoire.services.processor.get_extracted_pages", lambda p: None)
    # Permanent condition (retrying this task alone can't fix it) — must
    # raise TaskError so the dispatcher fails it outright instead of
    # retrying until max_attempts.
    with pytest.raises(TaskError):
        await handle_monster_extract_task(db, product, config={"system_profile": "dcc"})


async def test_handler_fails_with_unknown_profile(db, monkeypatch):
    product = await make_product(db, "/t/handler-badprofile.pdf")
    # No system_profile can ever make "gurps" a known id — permanent failure.
    with pytest.raises(TaskError):
        await handle_monster_extract_task(db, product, config={"system_profile": "gurps"})


async def test_handler_fails_when_no_provider_configured(db, monkeypatch):
    """No API key configured must fail loudly, not silently save zero rows as 'completed'."""
    product = await make_product(db, "/t/handler-noprovider.pdf")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("grimoire.services.processor.get_extracted_pages", lambda p: DCC_PAGES)

    with pytest.raises(TaskError):
        await handle_monster_extract_task(db, product, config={"system_profile": "dcc"})

    result = await db.execute(select(MonsterEntry).where(MonsterEntry.product_id == product.id))
    assert result.scalars().all() == []


async def test_handler_fails_when_every_candidate_errors(db, monkeypatch):
    """If every candidate raises (provider/transport trouble), fail rather than
    reporting success with nothing saved."""
    product = await make_product(db, "/t/handler-allfail.pdf")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("grimoire.services.processor.get_extracted_pages", lambda p: DCC_PAGES)

    async def failing_normalize(candidate, profile, provider=None, model=None):
        raise ValueError("transport error")

    monkeypatch.setattr("grimoire.processors.monster_normalizer.normalize_candidate", failing_normalize)

    with pytest.raises(TaskError):
        await handle_monster_extract_task(db, product, config={"system_profile": "dcc"})

    result = await db.execute(select(MonsterEntry).where(MonsterEntry.product_id == product.id))
    assert result.scalars().all() == []


async def test_rerun_replaces_pending_but_keeps_confirmed(db, monkeypatch):
    product = await make_product(db, "/t/handler-rerun.pdf")
    confirmed = MonsterEntry(product_id=product.id, review_status="confirmed",
                             **{k: v for k, v in fake_entry().items() if k != "review_status"})
    stale = MonsterEntry(product_id=product.id, review_status="pending",
                         **{k: v for k, v in fake_entry(name="Stale Ghost", page=99).items() if k != "review_status"})
    db.add_all([confirmed, stale])
    await db.flush()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("grimoire.services.processor.get_extracted_pages", lambda p: DCC_PAGES)

    async def fake_normalize(candidate, profile, provider=None, model=None):
        return fake_entry()  # same (name, page) as the confirmed row

    monkeypatch.setattr("grimoire.processors.monster_normalizer.normalize_candidate", fake_normalize)

    ok = await handle_monster_extract_task(db, product, config={"system_profile": "dcc"})
    assert ok is True
    result = await db.execute(select(MonsterEntry).where(MonsterEntry.product_id == product.id))
    entries = result.scalars().all()
    # Stale pending row deleted; confirmed kept; duplicate candidate skipped.
    assert len(entries) == 1
    assert entries[0].review_status == "confirmed"
