"""Tests for saved bestiary queries."""

import pytest
from fastapi import HTTPException

from grimoire.api.routes.monsters import (
    FavoriteRequest,
    create_favorite,
    delete_favorite,
    list_favorites,
    update_favorite,
)

SAMPLE_CONFIG = {
    "product_ids": [13, 27],
    "environment": "forest",
    "system_profile": "dcc",
    "hd_min": 1.0,
    "hd_max": 3.0,
    "q": None,
    "table_size": 8,
}


async def test_create_and_list_favorite_round_trips_config(db):
    created = await create_favorite(
        db=db, request=FavoriteRequest(name="Woodland low-level", config=SAMPLE_CONFIG)
    )
    assert created["name"] == "Woodland low-level"
    # config must survive the JSON-in-Text round trip exactly
    assert created["config"] == SAMPLE_CONFIG

    listed = await list_favorites(db=db)
    match = [f for f in listed["favorites"] if f["id"] == created["id"]]
    assert len(match) == 1
    assert match[0]["config"]["product_ids"] == [13, 27]
    assert match[0]["config"]["table_size"] == 8


async def test_update_favorite_renames_without_touching_config(db):
    created = await create_favorite(
        db=db, request=FavoriteRequest(name="Original Name", config=SAMPLE_CONFIG)
    )
    updated = await update_favorite(
        db=db, favorite_id=created["id"], request=FavoriteRequest(name="Renamed")
    )
    assert updated["name"] == "Renamed"
    assert updated["config"] == SAMPLE_CONFIG


async def test_update_favorite_overwrites_config(db):
    created = await create_favorite(
        db=db, request=FavoriteRequest(name="Overwrite Me", config=SAMPLE_CONFIG)
    )
    new_config = {**SAMPLE_CONFIG, "environment": "swamp", "table_size": 12}
    updated = await update_favorite(
        db=db, favorite_id=created["id"], request=FavoriteRequest(config=new_config)
    )
    assert updated["config"]["environment"] == "swamp"
    assert updated["config"]["table_size"] == 12
    assert updated["name"] == "Overwrite Me"


async def test_delete_favorite(db):
    created = await create_favorite(
        db=db, request=FavoriteRequest(name="Delete Me", config=SAMPLE_CONFIG)
    )
    result = await delete_favorite(db=db, favorite_id=created["id"])
    assert result["deleted"] is True

    listed = await list_favorites(db=db)
    assert all(f["id"] != created["id"] for f in listed["favorites"])


async def test_create_favorite_requires_a_name(db):
    with pytest.raises(HTTPException) as exc:
        await create_favorite(db=db, request=FavoriteRequest(config=SAMPLE_CONFIG))
    assert exc.value.status_code == 422


async def test_update_unknown_favorite_is_404(db):
    with pytest.raises(HTTPException) as exc:
        await update_favorite(db=db, favorite_id=99999999, request=FavoriteRequest(name="Ghost"))
    assert exc.value.status_code == 404
