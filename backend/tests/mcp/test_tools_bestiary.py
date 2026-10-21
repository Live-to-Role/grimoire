"""list_monsters returns pointers into owned books, never the stat block."""
from grimoire.mcp import tools_bestiary


async def test_list_monsters_confirmed_only_with_pointer_shape(db, library):
    out = await tools_bestiary.list_monsters(db)

    assert out["total"] == 1
    entry = out["results"][0]
    assert entry["name"] == "Bog Lurker"
    assert entry["book_title"] == "Marsh of Sorrows"
    assert entry["product_id"] == library["swamp"].id
    assert entry["page_number"] == 7
    assert entry["hd_dice"] == "3d8"
    assert entry["environments"] == ["swamp", "river"]
    for forbidden in ("raw_text", "attacks", "special_abilities"):
        assert forbidden not in entry


async def test_list_monsters_filters(db, library):
    assert (await tools_bestiary.list_monsters(db, environment="river"))["total"] == 1
    assert (await tools_bestiary.list_monsters(db, environment="desert"))["total"] == 0
    assert (await tools_bestiary.list_monsters(db, hd_min=4))["total"] == 0
    assert (await tools_bestiary.list_monsters(db, hd_min=2, hd_max=3))["total"] == 1
    assert (await tools_bestiary.list_monsters(db, name="lurk"))["total"] == 1
    assert (await tools_bestiary.list_monsters(db, product_id=library["sf1"].id))["total"] == 0
