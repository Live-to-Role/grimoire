"""Codex reclassification CLI: one subcommand per pipeline stage.

Nothing runs automatically; each stage is driven by hand in the order given in
docs/superpowers/plans/2026-10-25-codex-reclassification.md (Run sequence).

Usage (from backend/):
    C:/Users/mkemi/miniconda3/python.exe scripts/classify.py dump-codex
    C:/Users/mkemi/miniconda3/python.exe scripts/classify.py import-codex data/classification/codex_snapshot.csv
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "classification"


async def _with_session(fn):
    """Run fn(db) in a session against the live Grimoire database, then commit."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import grimoire.models  # noqa: F401 — registers every model with Base.metadata
    from grimoire.config import settings
    from grimoire.database import Base

    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        # The classification tables are new; create them if the app has not yet.
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            result = await fn(db)
            await db.commit()
            return result
    finally:
        await engine.dispose()


def cmd_dump_codex(args) -> None:
    from grimoire.services.classification.snapshot import dump_codex

    n = dump_codex(Path(args.out))
    print(f"{n} rows -> {args.out}")


def cmd_import_codex(args) -> None:
    from grimoire.services.classification.snapshot import import_snapshot

    n = asyncio.run(_with_session(lambda db: import_snapshot(db, Path(args.csv))))
    print(f"{n} rows")


def cmd_match(args) -> None:
    import csv

    from grimoire.services.classification.matching import match_all

    report = asyncio.run(_with_session(lambda db: match_all(db, args.fuzzy_threshold)))
    print(f"folder={report.folder} title={report.title} fuzzy={report.fuzzy} none={report.none}")
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["slug", "title", "publisher"])
        writer.writerows(report.unmatched)
    print(f"unmatched -> {out}")


def cmd_excerpt(args) -> None:
    import json

    from sqlalchemy import select

    from grimoire.models import Product
    from grimoire.models.classification import CodexProduct
    from grimoire.services.classification.excerpt import build_description_excerpt, build_excerpt

    async def run(db):
        cp = (await db.execute(select(CodexProduct).where(CodexProduct.slug == args.slug))).scalar_one()
        product = await db.get(Product, cp.grimoire_product_id) if cp.grimoire_product_id else None
        if product is None or not product.extracted_text_path:
            return build_description_excerpt(cp)
        with open(product.extracted_text_path, encoding="utf-8") as f:
            text_json = json.load(f)
        return build_excerpt(text_json, {"filename": product.file_name, "codex_title": cp.title})

    ex = asyncio.run(_with_session(run))
    sys.stdout.reconfigure(encoding="utf-8")
    print(ex.text)
    print(f"[source={ex.source} windows={ex.windows} unpaged={ex.unpaged} tokens={ex.tokens} chars={len(ex.text)}]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("dump-codex", help="dump the Codex catalog to CSV")
    p.add_argument("--out", default=str(DATA_DIR / "codex_snapshot.csv"))
    p.set_defaults(func=cmd_dump_codex)

    p = sub.add_parser("import-codex", help="upsert a Codex snapshot CSV")
    p.add_argument("csv")
    p.set_defaults(func=cmd_import_codex)

    p = sub.add_parser("match", help="match Codex products to Grimoire files")
    p.add_argument("--fuzzy-threshold", type=int, default=90)
    p.add_argument("--report", default=str(DATA_DIR / "unmatched.csv"))
    p.set_defaults(func=cmd_match)

    p = sub.add_parser("excerpt", help="print the excerpt for one Codex product, for eyeballing")
    p.add_argument("slug")
    p.set_defaults(func=cmd_excerpt)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
