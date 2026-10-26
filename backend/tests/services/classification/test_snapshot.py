from pathlib import Path

import pytest

from grimoire.models import CodexProduct
from grimoire.services.classification.snapshot import SNAPSHOT_SQL, import_snapshot

FIXTURE = Path(__file__).parents[2] / "fixtures" / "classification" / "codex_snapshot.csv"
LEVELS_ID = "00000000-0000-0000-0000-000000000003"


@pytest.fixture
def snapshot_csv():
    return FIXTURE


async def test_import_snapshot_upserts_and_preserves_match(db, snapshot_csv):
    assert await import_snapshot(db, snapshot_csv) == 6
    cp = await db.get(CodexProduct, LEVELS_ID)
    assert (cp.level_range_min, cp.level_range_max) == (1, 3)
    cp.grimoire_product_id = 42
    cp.match_method = "folder"
    cp.in_pilot = True
    await db.flush()

    assert await import_snapshot(db, snapshot_csv) == 6
    cp = await db.get(CodexProduct, LEVELS_ID)
    assert cp.grimoire_product_id == 42 and cp.match_method == "folder" and cp.in_pilot is True


async def test_import_keeps_level_zero(db, snapshot_csv):
    await import_snapshot(db, snapshot_csv)
    cp = await db.get(CodexProduct, "00000000-0000-0000-0000-000000000006")
    assert (cp.level_range_min, cp.level_range_max) == (0, 0)


async def test_import_blank_publisher_is_none(db, snapshot_csv):
    await import_snapshot(db, snapshot_csv)
    cp = await db.get(CodexProduct, "00000000-0000-0000-0000-000000000004")
    assert cp.publisher is None and cp.dtrpg_id is None and cp.description is None
    cp1 = await db.get(CodexProduct, "00000000-0000-0000-0000-000000000001")
    assert cp1.description.startswith('A set of beach encounters, with "quotes"')
    assert cp1.page_count == 12


def test_snapshot_sql_selects_description():
    assert "p.description" in SNAPSHOT_SQL and "catalog_publisher" in SNAPSHOT_SQL
