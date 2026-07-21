"""Tests for the MonsterEntry model."""

import json

from sqlalchemy import select

from grimoire.models import MonsterEntry, Product


async def test_create_monster_entry(db):
    product = Product(
        file_path="/t/bestiary-model-test.pdf",
        file_name="bestiary-model-test.pdf",
        file_size=1,
        file_hash="mh1",
    )
    db.add(product)
    await db.flush()

    entry = MonsterEntry(
        product_id=product.id,
        name="Peryton",
        page_number=142,
        system_profile="osr",
        raw_text="PERYTON\nAC 7 [12], HD 4 ...",
        ac=12,
        hd_dice="4d8",
        hd_value=4.0,
        hp_avg=18.0,
        attacks=json.dumps([{"name": "antlers", "bonus": 4, "damage_dice": "2d4", "damage_avg": 5.0}]),
        move="240' flying",
        special_abilities=json.dumps(["heart-eating"]),
        environments=json.dumps(["mountains", "wilderness"]),
        extraction_confidence=0.9,
        flags=json.dumps([]),
        review_status="pending",
    )
    db.add(entry)
    await db.flush()

    result = await db.execute(select(MonsterEntry).where(MonsterEntry.name == "Peryton"))
    saved = result.scalar_one()
    assert saved.product_id == product.id
    assert saved.review_status == "pending"
    assert json.loads(saved.environments) == ["mountains", "wilderness"]
