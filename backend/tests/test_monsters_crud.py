"""Tests for hand create / clear-on-patch / delete of bestiary entries."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from grimoire.api.routes.monsters import (
    CreateEntryRequest,
    create_entry,
)
from grimoire.models import MonsterEntry, Product


async def make_product(db, path):
    product = Product(file_path=path, file_name=path.rsplit("/", 1)[-1],
                      file_size=1, file_hash=path, title="Test Bestiary",
                      text_extracted=True, extracted_text_path="/t/x.json")
    db.add(product)
    await db.flush()
    return product


async def test_create_happy_path(db):
    product = await make_product(db, "/t/crud-create-1.pdf")
    result = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Giant Clam", system_profile="dcc",
        page_number=109, ac=26, hd_dice="5d6", move="0'",
        attacks=[], special_abilities=[], environments=["aquatic"],
        raw_text="source excerpt",
    ))
    assert result["name"] == "Giant Clam"
    assert result["product_id"] == product.id
    assert result["page_number"] == 109
    assert result["ac"] == 26
    assert result["move"] == "0'"
    assert result["environments"] == ["aquatic"]
    assert result["raw_text"] == "source excerpt"

    stored = (await db.execute(
        select(MonsterEntry).where(MonsterEntry.id == result["id"])
    )).scalar_one()
    assert stored.name == "Giant Clam"


async def test_create_derives_stats_like_extraction(db):
    product = await make_product(db, "/t/crud-create-2.pdf")
    result = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Cone Snail", system_profile="dcc",
        hd_dice="3d6",
        attacks=[{"name": "sting", "bonus": 2, "damage_dice": "1d4"}],
    ))
    assert result["hp_avg"] == 10.5
    assert result["hd_value"] == 3.0
    assert result["attacks"][0]["damage_avg"] == 2.5
    assert result["flags"] == []


async def test_create_flags_like_extraction(db):
    product = await make_product(db, "/t/crud-create-3.pdf")
    result = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Blob", system_profile="dcc", hd_dice="2d8",
    ))
    assert result["flags"] == ["no_attacks"]


async def test_create_is_confirmed_with_null_confidence(db):
    product = await make_product(db, "/t/crud-create-4.pdf")
    result = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Hand Typed", system_profile="dcc",
    ))
    assert result["review_status"] == "confirmed"
    assert result["extraction_confidence"] is None


async def test_create_rejects_unknown_product(db):
    with pytest.raises(HTTPException) as exc:
        await create_entry(db=db, request=CreateEntryRequest(
            product_id=999999, name="Ghost", system_profile="dcc",
        ))
    assert exc.value.status_code == 404


async def test_create_rejects_unknown_profile(db):
    product = await make_product(db, "/t/crud-create-5.pdf")
    with pytest.raises(HTTPException) as exc:
        await create_entry(db=db, request=CreateEntryRequest(
            product_id=product.id, name="Ghost", system_profile="pathfinder",
        ))
    assert exc.value.status_code == 400


async def test_create_rejects_blank_name(db):
    product = await make_product(db, "/t/crud-create-6.pdf")
    with pytest.raises(HTTPException) as exc:
        await create_entry(db=db, request=CreateEntryRequest(
            product_id=product.id, name="   ", system_profile="dcc",
        ))
    assert exc.value.status_code == 422


async def test_create_defaults_raw_text_to_empty_string(db):
    product = await make_product(db, "/t/crud-create-7.pdf")
    result = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="No Source", system_profile="dcc",
    ))
    # raw_text is NOT NULL in the model; an omitted excerpt stores "".
    assert result["raw_text"] == ""
