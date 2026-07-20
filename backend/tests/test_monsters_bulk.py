"""Tests for bulk review-status updates."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from grimoire.api.routes.monsters import BulkStatusRequest, bulk_status
from grimoire.models import MonsterEntry, Product


async def seed_entries(db, path, names, status="pending"):
    product = Product(
        file_path=path, file_name=path.rsplit("/", 1)[-1],
        file_size=1, file_hash=path, title="Bulk Test Book",
    )
    db.add(product)
    await db.flush()
    entries = []
    for name in names:
        entry = MonsterEntry(
            product_id=product.id, name=name, page_number=1, system_profile="dcc",
            raw_text="raw", ac=12, hd_dice="1d8", hd_value=1.0, hp_avg=4.5,
            attacks=json.dumps([]), environments=json.dumps([]),
            special_abilities=json.dumps([]), flags=json.dumps([]),
            review_status=status,
        )
        db.add(entry)
        entries.append(entry)
    await db.flush()
    return product, entries


async def test_bulk_confirm_updates_all_given_ids(db):
    _, entries = await seed_entries(db, "/t/bulk-confirm.pdf", ["Bulk Orc", "Bulk Rat", "Bulk Bat"])
    ids = [e.id for e in entries]

    result = await bulk_status(db=db, request=BulkStatusRequest(ids=ids, review_status="confirmed"))
    assert result["updated"] == 3

    rows = (await db.execute(select(MonsterEntry).where(MonsterEntry.id.in_(ids)))).scalars().all()
    assert {r.review_status for r in rows} == {"confirmed"}


async def test_bulk_leaves_unlisted_entries_alone(db):
    _, entries = await seed_entries(db, "/t/bulk-partial.pdf", ["Keep Me", "Change Me"])
    keep, change = entries

    result = await bulk_status(db=db, request=BulkStatusRequest(ids=[change.id], review_status="rejected"))
    assert result["updated"] == 1

    await db.refresh(keep)
    await db.refresh(change)
    assert keep.review_status == "pending"
    assert change.review_status == "rejected"


async def test_bulk_rejects_invalid_status(db):
    _, entries = await seed_entries(db, "/t/bulk-badstatus.pdf", ["Bad Status Orc"])
    with pytest.raises(HTTPException) as exc:
        await bulk_status(db=db, request=BulkStatusRequest(ids=[entries[0].id], review_status="maybe"))
    assert exc.value.status_code == 422


async def test_bulk_empty_ids_is_a_noop(db):
    result = await bulk_status(db=db, request=BulkStatusRequest(ids=[], review_status="confirmed"))
    assert result["updated"] == 0


async def test_bulk_unknown_ids_are_skipped(db):
    _, entries = await seed_entries(db, "/t/bulk-unknown.pdf", ["Real Orc"])
    result = await bulk_status(
        db=db, request=BulkStatusRequest(ids=[entries[0].id, 99999999], review_status="confirmed")
    )
    # Only the row that exists is counted, so a caller can detect a mismatch.
    assert result["updated"] == 1
