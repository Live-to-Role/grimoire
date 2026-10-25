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


# Output per request (JSON plus adaptive thinking), from the spec's cost estimate.
# Replace with the pilot's measured output_tokens / request_count once known.
EST_OUTPUT_TOKENS = 500


def _anthropic_client(db):
    import anthropic

    from grimoire.services.classification.batch import anthropic_api_key

    async def make():
        return anthropic.Anthropic(api_key=await anthropic_api_key(db))

    return make()


def cmd_submit(args) -> None:
    from grimoire.services.classification.batch import BATCH_PRICES, build_items, submit_run
    from grimoire.services.classification.excerpt import estimate_tokens
    from grimoire.services.classification.prompt import SYSTEM_PROMPT

    slugs = Path(args.slugs).read_text(encoding="utf-8").split() if args.slugs else None

    async def run(db):
        items = await build_items(db, pilot=args.pilot, all_=args.all, slugs=slugs)
        n = len(items)
        tokens_in = sum(i.excerpt.tokens for i in items) + n * estimate_tokens(SYSTEM_PROMPT)
        tokens_out = n * EST_OUTPUT_TOKENS
        price_in, price_out = BATCH_PRICES[args.model]
        projected = tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
        descriptions = sum(1 for i in items if i.source == "description")
        print(f"{n} requests ({descriptions} description-only), ~{tokens_in:,} input tokens, "
              f"~{tokens_out:,} output tokens (est.), projected ${projected:.2f} on {args.model}")
        if args.dry_run or n == 0:
            print("not sent")
            return
        client = await _anthropic_client(db)
        r = await submit_run(db, client, args.run, args.model, args.effort, items)
        print(f"run {r.name}: batch {r.batch_id}")

    asyncio.run(_with_session(run))


def cmd_collect(args) -> None:
    from sqlalchemy import select

    from grimoire.models.classification import ClassificationRun
    from grimoire.services.classification.batch import collect_run

    async def run(db):
        client = await _anthropic_client(db)
        counts = await collect_run(db, client, args.run, wait=args.wait)
        print(counts)
        r = (await db.execute(select(ClassificationRun).where(ClassificationRun.name == args.run))).scalar_one()
        if r.status == "collected":
            per = r.cost_usd / r.request_count if r.request_count else 0
            print(f"{r.input_tokens:,} input / {r.output_tokens:,} output tokens, "
                  f"${r.cost_usd:.2f} (${per:.4f} per product)")

    asyncio.run(_with_session(run))


def cmd_select_pilot(args) -> None:
    from collections import Counter

    from sqlalchemy import select

    from grimoire.models.classification import CodexProduct
    from grimoire.services.classification.pilot import select_pilot

    async def run(db):
        slugs = await select_pilot(db, n=args.n, seed=args.seed)
        rows = (await db.execute(select(CodexProduct).where(CodexProduct.in_pilot.is_(True)))).scalars()
        by = Counter("description" if r.match_method == "none" else (r.product_type or "(blank)")
                     for r in rows)
        return slugs, by

    slugs, by = asyncio.run(_with_session(run))
    print(f"{len(slugs)} pilot products")
    for key, count in by.most_common():
        print(f"  {key}: {count}")


def cmd_pilot_sheet(args) -> None:
    from grimoire.services.classification.pilot import write_pilot_sheet

    out = Path(args.out)
    excerpt_dir = out.parent / "pilot_excerpts"
    runs = args.runs.split(",")
    n = asyncio.run(_with_session(lambda db: write_pilot_sheet(db, runs, out, excerpt_dir)))
    print(f"{n} rows -> {out}; excerpts in {excerpt_dir}")


def cmd_pilot_score(args) -> None:
    from grimoire.services.classification.pilot import score_pilot

    runs = args.runs.split(",")
    scores = asyncio.run(_with_session(lambda db: score_pilot(db, runs, Path(args.truth))))
    print(f"{'run':<16}{'n':>5}{'type':>8}{'levels':>8}{'lvl FP':>8}{'$/product':>11}{'full run':>10}")
    for s in scores:
        full = s.cost_per_product * args.full_count
        print(f"{s.run:<16}{s.n:>5}{s.type_accuracy:>8.1%}{s.level_exact:>8.1%}"
              f"{s.level_false_positive:>8.1%}{s.cost_per_product:>11.4f}{full:>10.2f}")


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

    p = sub.add_parser("submit", help="send a classification run to the Batches API")
    p.add_argument("--run", required=True)
    p.add_argument("--model", required=True, choices=["claude-sonnet-5-5", "claude-opus-5-5"])
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    which = p.add_mutually_exclusive_group(required=True)
    which.add_argument("--pilot", action="store_true")
    which.add_argument("--all", action="store_true")
    which.add_argument("--slugs", help="file of Codex slugs, whitespace-separated")
    p.add_argument("--dry-run", action="store_true", help="print the projection, send nothing")
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("collect", help="store a run's batch results")
    p.add_argument("--run", required=True)
    p.add_argument("--wait", action="store_true", help="poll every 60 s until the batches end")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("select-pilot", help="pick the hand-labelled pilot products")
    p.add_argument("--n", type=int, default=150)
    p.add_argument("--seed", type=int, default=20261025)
    p.set_defaults(func=cmd_select_pilot)

    p = sub.add_parser("pilot-sheet", help="write the pilot label sheet and excerpts")
    p.add_argument("--runs", required=True, help="comma-separated run names")
    p.add_argument("--out", default=str(DATA_DIR / "pilot.csv"))
    p.set_defaults(func=cmd_pilot_sheet)

    p = sub.add_parser("pilot-score", help="score runs against the labelled pilot sheet")
    p.add_argument("--runs", required=True, help="comma-separated run names")
    p.add_argument("--truth", required=True)
    p.add_argument("--full-count", type=int, default=7327, help="products in the full run")
    p.set_defaults(func=cmd_pilot_score)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
