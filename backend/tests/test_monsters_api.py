"""Tests for bestiary API routes (called directly with the db fixture)."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from grimoire.api.routes.monsters import (
    ExtractRequest,
    PatchEntryRequest,
    RandomRequest,
    enqueue_extract,
    get_entry_metrics,
    list_environments,
    list_monsters,
    patch_entry,
    random_monsters,
)
from grimoire.models import MonsterEntry, ProcessingQueue, Product


async def seed(db, path, name, env, status="confirmed", hd_value=1.0):
    product = Product(file_path=path, file_name=path.rsplit("/", 1)[-1],
                      file_size=1, file_hash=path, title="Test Bestiary",
                      text_extracted=True, extracted_text_path="/t/x.json")
    db.add(product)
    await db.flush()
    entry = MonsterEntry(
        product_id=product.id, name=name, page_number=10, system_profile="dcc",
        raw_text="raw", ac=13, hd_dice="1d8", hd_value=hd_value, hp_avg=4.5,
        attacks=json.dumps([{"name": "claw", "bonus": 1, "damage_dice": "1d4", "damage_avg": 2.5}]),
        environments=json.dumps([env]), special_abilities=json.dumps([]),
        flags=json.dumps([]), review_status=status,
    )
    db.add(entry)
    await db.flush()
    return product, entry


async def test_list_filters_by_environment_and_default_confirmed(db):
    await seed(db, "/t/api-list-1.pdf", "Forest Wolf", "forest")
    await seed(db, "/t/api-list-2.pdf", "Cave Ooze", "underground")
    await seed(db, "/t/api-list-3.pdf", "Pending Rat", "forest", status="pending")

    result = await list_monsters(db=db, environment="forest")
    names = [item["name"] for item in result["items"]]
    assert "Forest Wolf" in names
    assert "Cave Ooze" not in names
    assert "Pending Rat" not in names  # default review_status=confirmed

    pending = await list_monsters(db=db, environment="forest", review_status="pending")
    assert [i["name"] for i in pending["items"]] == ["Pending Rat"]


async def test_hd_range_filter(db):
    await seed(db, "/t/api-hd-1.pdf", "Big Troll", "hills", hd_value=6.0)
    result = await list_monsters(db=db, hd_min=5.0)
    names = [i["name"] for i in result["items"]]
    assert "Big Troll" in names
    assert all(i["hd_value"] >= 5.0 for i in result["items"])


async def test_patch_recomputes_derived_fields(db):
    _, entry = await seed(db, "/t/api-patch.pdf", "Patch Me", "swamp")
    updated = await patch_entry(
        db=db, entry_id=entry.id,
        request=PatchEntryRequest(hd_dice="3d8+3", review_status="confirmed"),
    )
    assert updated["hp_avg"] == 16.5
    assert updated["hd_value"] == 3.0
    assert updated["review_status"] == "confirmed"


async def test_patch_rejects_bad_status(db):
    _, entry = await seed(db, "/t/api-badstatus.pdf", "Bad Status", "swamp")
    with pytest.raises(HTTPException) as exc:
        await patch_entry(db=db, entry_id=entry.id, request=PatchEntryRequest(review_status="maybe"))
    assert exc.value.status_code == 422


async def test_metrics_endpoint(db):
    _, entry = await seed(db, "/t/api-metrics.pdf", "Metric Orc", "plains")
    metrics = await get_entry_metrics(db=db, entry_id=entry.id)
    assert metrics["hp_avg"] == 4.5
    assert metrics["tiers"][0]["tier"] == "unarmored"


async def test_random_returns_only_confirmed_with_product_title(db):
    await seed(db, "/t/api-rand-1.pdf", "Rand Wolf", "tundra")
    await seed(db, "/t/api-rand-2.pdf", "Rand Ghost", "tundra", status="pending")
    result = await random_monsters(db=db, request=RandomRequest(count=10, environment="tundra"))
    names = [i["name"] for i in result["items"]]
    assert "Rand Wolf" in names
    assert "Rand Ghost" not in names
    assert all(i["product_title"] for i in result["items"])


async def test_enqueue_extract(db):
    product, _ = await seed(db, "/t/api-enq.pdf", "Enq Orc", "forest")
    response = await enqueue_extract(
        db=db, product_id=product.id, request=ExtractRequest(system_profile="dcc")
    )
    assert response["queued"] is True
    result = await db.execute(select(ProcessingQueue).where(
        ProcessingQueue.product_id == product.id,
        ProcessingQueue.task_type == "monster_extract",
    ))
    item = result.scalars().first()
    assert item is not None
    assert json.loads(item.config)["system_profile"] == "dcc"

    again = await enqueue_extract(
        db=db, product_id=product.id, request=ExtractRequest(system_profile="dcc")
    )
    assert again["queued"] is False


async def test_enqueue_rejects_unknown_profile(db):
    product, _ = await seed(db, "/t/api-enq-bad.pdf", "Bad Prof", "forest")
    with pytest.raises(HTTPException) as exc:
        await enqueue_extract(db=db, product_id=product.id, request=ExtractRequest(system_profile="gurps"))
    assert exc.value.status_code == 400


async def test_environments_listing(db):
    await seed(db, "/t/api-envs.pdf", "Env Crab", "coastal")
    envs = await list_environments(db=db)
    assert "coastal" in envs["environments"]
