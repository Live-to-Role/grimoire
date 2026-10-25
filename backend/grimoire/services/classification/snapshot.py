"""Snapshot of the Codex catalog, pulled from its Postgres and kept locally.

The export diffs against this snapshot, so it is re-taken immediately before a
live export. Match results live on the same rows and survive re-imports.
"""

import csv
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models.classification import CodexProduct

SNAPSHOT_SQL = (
    "select p.id, p.slug, p.title, pub.name as publisher, p.product_type, "
    "p.level_range_min, p.level_range_max, p.dtrpg_id, p.page_count, p.description "
    "from catalog_product p left join catalog_publisher pub on pub.id = p.publisher_id "
    "order by p.slug"
)

# The railway CLI link is per-directory and lives at the grimoire repo root.
REPO_ROOT = Path(__file__).resolve().parents[4]

_STR_FIELDS = ("slug", "title", "publisher", "product_type", "dtrpg_id", "description")
_INT_FIELDS = ("level_range_min", "level_range_max", "page_count")


def _database_url() -> str:
    out = subprocess.run(
        # railway is an npm .cmd shim on Windows; resolve it so no shell is needed.
        [shutil.which("railway") or "railway", "variables", "--service", "Postgres", "--kv"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    ).stdout
    for line in out.splitlines():
        key, _, value = line.partition("=")
        if key == "DATABASE_PUBLIC_URL":
            return value.strip()
    raise RuntimeError("DATABASE_PUBLIC_URL not found in railway variables")


def _count_rows(csv_path: Path) -> int:
    # Descriptions contain newlines, so count records, not lines.
    with open(csv_path, encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def dump_codex(out_path: Path) -> int:
    """Dump the Codex catalog to CSV via psql. Never prints the database URL."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target = out_path.resolve().as_posix()
    copy = f"\\copy ({SNAPSHOT_SQL}) to '{target}' csv header"
    subprocess.run(
        ["psql", _database_url(), "-c", copy],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )
    return _count_rows(out_path)


def _parse_row(row: dict[str, str]) -> dict:
    values: dict = {}
    for field in _STR_FIELDS:
        values[field] = row.get(field) or None
    for field in _INT_FIELDS:
        raw = (row.get(field) or "").strip()
        values[field] = int(raw) if raw else None
    return values


async def import_snapshot(db: AsyncSession, csv_path: Path) -> int:
    """Upsert the snapshot by Codex id, keeping match and pilot columns."""
    existing = {
        cp.id: cp for cp in (await db.execute(select(CodexProduct))).scalars()
    }
    count = 0
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            values = _parse_row(row)
            cp = existing.get(row["id"])
            if cp is None:
                db.add(CodexProduct(id=row["id"], **values))
            else:
                for field, value in values.items():
                    setattr(cp, field, value)
            count += 1
    await db.flush()
    return count
