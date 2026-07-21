"""Tests for the wrong-profile extraction guard."""

import pytest
from fastapi import HTTPException

from grimoire.api.routes.monsters import ExtractRequest, enqueue_extract
from grimoire.models import Product
from grimoire.services.queue_processor import TaskError, handle_monster_extract_task

# A DCC inline stat line - what the dcc profile's anchor is built for.
DCC_MARKDOWN = (
    "## Orc\n\nRaiders of the wastes.\n\n"
    "Orc: Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; MV 30'; Act 1d20; "
    "SV Fort +1, Ref +0, Will -1; AL C.\n"
)

# A D&D 5e stat block - no "Init +N", no "HD NdN", so no profile matches it.
FIVE_E_MARKDOWN = (
    "AKLASH\nLarge monstrosity, neutral\n"
    "Armor Class 11 (natural armor)\n"
    "Hit Points 51 (6d10 + 18)\n"
    "Speed 30 ft.\n"
    "Challenge 2\n"
)


async def make_product(db, path, title, extracted=True):
    product = Product(
        file_path=path, file_name=path.rsplit("/", 1)[-1], file_size=1,
        file_hash=path, title=title, text_extracted=extracted,
        extracted_text_path="/t/does-not-matter.json" if extracted else None,
    )
    db.add(product)
    await db.flush()
    return product


async def test_guard_blocks_when_no_profile_matches(db, monkeypatch):
    """A 5e bestiary queued as DCC must be refused, not silently completed."""
    product = await make_product(db, "/t/guard-5e.pdf", "5E Bestiary")
    monkeypatch.setattr(
        "grimoire.services.processor.get_extracted_pages",
        lambda p: [{"page": 1, "markdown": FIVE_E_MARKDOWN}],
    )

    with pytest.raises(HTTPException) as exc:
        await enqueue_extract(db=db, product_id=product.id, request=ExtractRequest(system_profile="dcc"))
    assert exc.value.status_code == 400
    assert "stat block" in exc.value.detail.lower()


async def test_guard_allows_a_matching_profile(db, monkeypatch):
    product = await make_product(db, "/t/guard-dcc.pdf", "DCC Bestiary")
    monkeypatch.setattr(
        "grimoire.services.processor.get_extracted_pages",
        lambda p: [{"page": n, "markdown": DCC_MARKDOWN} for n in range(1, 6)],
    )

    result = await enqueue_extract(
        db=db, product_id=product.id, request=ExtractRequest(system_profile="dcc")
    )
    assert result["queued"] is True
    assert result["counts"]["dcc"] > 0
    assert "warning" not in result


async def test_guard_reports_counts_for_every_profile(db, monkeypatch):
    product = await make_product(db, "/t/guard-counts.pdf", "Counts Bestiary")
    monkeypatch.setattr(
        "grimoire.services.processor.get_extracted_pages",
        lambda p: [{"page": n, "markdown": DCC_MARKDOWN} for n in range(1, 4)],
    )

    result = await enqueue_extract(
        db=db, product_id=product.id, request=ExtractRequest(system_profile="dcc")
    )
    assert set(result["counts"].keys()) == {"dcc", "osr"}


async def test_handler_fails_on_zero_candidates(db, monkeypatch):
    """Zero candidates must not report success - that is the silent failure."""
    product = await make_product(db, "/t/guard-handler-zero.pdf", "Zero Candidates")
    monkeypatch.setattr(
        "grimoire.services.processor.get_extracted_pages",
        lambda p: [{"page": 1, "markdown": FIVE_E_MARKDOWN}],
    )

    async def _no_db_key(key_name):
        return "unused-because-we-fail-first"

    monkeypatch.setattr(
        "grimoire.processors.monster_normalizer.get_setting_from_db", _no_db_key
    )

    with pytest.raises(TaskError):
        await handle_monster_extract_task(db, product, config={"system_profile": "dcc"})
