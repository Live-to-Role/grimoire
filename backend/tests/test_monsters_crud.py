"""Tests for hand create / clear-on-patch / delete of bestiary entries."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from grimoire.api.routes.monsters import (
    CreateEntryRequest,
    PatchEntryRequest,
    create_entry,
    delete_entry,
    patch_entry,
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


async def test_patch_clears_field_when_null_sent_explicitly(db):
    product = await make_product(db, "/t/crud-patch-1.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Clearable", system_profile="dcc",
        ac=13, hd_dice="1d8", move="30'",
    ))
    assert created["ac"] == 13

    result = await patch_entry(
        db=db, entry_id=created["id"],
        # model_validate on an explicit dict is what marks `ac` as "set"
        request=PatchEntryRequest.model_validate({"ac": None}),
    )
    assert result["ac"] is None
    # Untouched fields survive
    assert result["hd_dice"] == "1d8"
    assert result["move"] == "30'"


async def test_patch_leaves_absent_fields_alone(db):
    product = await make_product(db, "/t/crud-patch-2.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Untouched", system_profile="dcc",
        ac=13, hd_dice="1d8", move="30'", environments=["forest"],
    ))
    result = await patch_entry(
        db=db, entry_id=created["id"],
        request=PatchEntryRequest.model_validate({"name": "Renamed"}),
    )
    assert result["name"] == "Renamed"
    assert result["ac"] == 13
    assert result["hd_dice"] == "1d8"
    assert result["move"] == "30'"
    assert result["environments"] == ["forest"]


async def test_patch_clearing_hd_clears_derived_fields(db):
    product = await make_product(db, "/t/crud-patch-3.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Dice Gone", system_profile="dcc", hd_dice="3d6",
    ))
    assert created["hp_avg"] == 10.5

    result = await patch_entry(
        db=db, entry_id=created["id"],
        request=PatchEntryRequest.model_validate({"hd_dice": None}),
    )
    assert result["hd_dice"] is None
    assert result["hp_avg"] is None
    assert result["hd_value"] is None


async def test_patch_recomputes_flags(db):
    product = await make_product(db, "/t/crud-patch-4.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Flagged", system_profile="dcc", hd_dice="1d8",
    ))
    assert created["flags"] == ["no_attacks"]

    result = await patch_entry(
        db=db, entry_id=created["id"],
        request=PatchEntryRequest.model_validate({
            "attacks": [{"name": "bite", "bonus": 1, "damage_dice": "1d6"}],
        }),
    )
    assert result["flags"] == []
    assert result["attacks"][0]["damage_avg"] == 3.5


async def test_patch_rejects_explicit_null_review_status(db):
    product = await make_product(db, "/t/crud-patch-5.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Status Guard", system_profile="dcc",
    ))
    with pytest.raises(HTTPException) as exc:
        await patch_entry(
            db=db, entry_id=created["id"],
            request=PatchEntryRequest.model_validate({"review_status": None}),
        )
    assert exc.value.status_code == 422


async def test_delete_removes_the_row(db):
    product = await make_product(db, "/t/crud-delete-1.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Mistake", system_profile="dcc",
    ))
    result = await delete_entry(db=db, entry_id=created["id"])
    assert result == {"deleted": True}

    gone = (await db.execute(
        select(MonsterEntry).where(MonsterEntry.id == created["id"])
    )).scalar_one_or_none()
    assert gone is None


async def test_delete_unknown_id_is_404(db):
    with pytest.raises(HTTPException) as exc:
        await delete_entry(db=db, entry_id=999999)
    assert exc.value.status_code == 404
