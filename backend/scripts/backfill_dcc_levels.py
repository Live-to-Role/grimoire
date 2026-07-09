"""Backfill level_range_min/max for Dungeon Crawl Classics products from the
checked-in Wikipedia module-list snapshot (scripts/data/dcc_module_levels.csv).

Only writes rows where BOTH level fields are currently NULL. Level 0 is a real
value (funnel adventures). Idempotent. --dry-run prints the match table only.

Usage (from backend/):
    C:/Users/mkemi/miniconda3/python.exe scripts/backfill_dcc_levels.py --dry-run
    C:/Users/mkemi/miniconda3/python.exe scripts/backfill_dcc_levels.py
"""

import argparse
import asyncio
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_MODULE_NUM_RE = re.compile(r"dcc\W{0,3}#?\s*0*(\d+\.\d+(?!\d)|\d+\b)", re.IGNORECASE)

# Products the user reviewed in the dry-run and chose to exclude: a rules
# sourcebook false-matched by module number, plus map/card/DM-screen
# accessories that are not the adventure itself (would inherit a misleading
# level). Matched by exact file_name.
_EXCLUDED_FILE_NAMES = {
    "DCC3-AdvancedEquipmentOptions.pdf",
    "DCC54-Card-Inserts.pdf",
    "DCC55-Maps.pdf",
    "DCC39-DM-Screen-2.pdf",
}


def parse_module_number(text: str) -> str | None:
    """Extract a DCC module number ('DCC #67', 'DCC 067', 'dcc-035', 'DCC #91.1')
    as a canonical no-leading-zeros string (decimal sub-module suffix preserved
    verbatim, e.g. '91.1'), or None.

    The integer-only branch requires a trailing word boundary (rejects e.g.
    'dcc35a.pdf' as ambiguous). The decimal branch does NOT require one,
    because real file names glue the sub-module suffix directly onto the
    title with no separator (e.g. 'DCC91.1Barako.pdf' -> '91.1')."""
    m = _MODULE_NUM_RE.search(text or "")
    return m.group(1) if m else None


def normalize_title(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (text or "").lower())).strip()


def load_csv() -> dict:
    """number -> (title, level_min, level_max); also returns title index."""
    path = Path(__file__).parent / "data" / "dcc_module_levels.csv"
    by_number: dict[str, tuple[str, int, int]] = {}
    by_title: dict[str, tuple[str, int, int]] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            entry = (row["title"], int(row["level_min"]), int(row["level_max"]))
            num = str(int(row["number"])) if row["number"].strip().isdigit() else row["number"].strip()
            by_number[num] = entry
            by_title[normalize_title(row["title"])] = entry
    return {"by_number": by_number, "by_title": by_title}


async def run(dry_run: bool) -> None:
    from sqlalchemy import or_, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from grimoire.config import settings
    from grimoire.models import Product

    data = load_csv()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine)

    async with session_factory() as db:
        result = await db.execute(
            select(Product).where(
                Product.level_range_min.is_(None),
                Product.level_range_max.is_(None),
                or_(
                    Product.game_system.ilike("%dungeon crawl%"),
                    Product.game_system.ilike("%dcc%"),
                    Product.title.ilike("%dcc%"),
                    Product.file_name.ilike("%dcc%"),
                ),
            )
        )
        candidates = result.scalars().all()
        print(f"{len(candidates)} DCC-ish products with NULL level range")

        matched, unmatched = [], []
        for p in candidates:
            if p.file_name in _EXCLUDED_FILE_NAMES:
                print(f"  [       EXCLUDED] title={p.title!r} file={p.file_name!r}")
                continue
            entry = None
            how = ""
            num = parse_module_number(p.title or "") or parse_module_number(p.file_name or "")
            if num and num in data["by_number"]:
                entry = data["by_number"][num]
                how = f"#{num}"
            else:
                norm = normalize_title(p.title or "")
                if norm and norm in data["by_title"]:
                    entry = data["by_title"][norm]
                    how = "title"
                else:
                    hits = [e for t, e in data["by_title"].items() if t and t in norm] if norm else []
                    if len(hits) == 1:
                        entry, how = hits[0], "title-contains"
                    elif len(hits) > 1:
                        print(f"  AMBIGUOUS (skipped): {p.title!r} matches {len(hits)} modules")
                        continue
            if entry:
                matched.append((p, entry, how))
            else:
                unmatched.append(p)

        for p, (csv_title, lmin, lmax), how in matched:
            print(
                f"  [{how:>14}] title={p.title!r} file={p.file_name!r} "
                f"-> levels {lmin}-{lmax} ({csv_title})"
            )
            if not dry_run:
                p.level_range_min = lmin
                p.level_range_max = lmax

        if unmatched:
            print(f"\n{len(unmatched)} candidates had no match (left untouched):")
            for p in unmatched[:30]:
                print(f"  - {p.title or p.file_name}")

        if dry_run:
            print(f"\nDRY RUN: would update {len(matched)} products")
        else:
            await db.commit()
            print(f"\nUpdated {len(matched)} products")

    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    asyncio.run(run(ap.parse_args().dry_run))
