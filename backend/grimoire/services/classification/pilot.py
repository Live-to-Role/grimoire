"""The hand-labelled pilot: pick 150 products, write a label sheet, score runs.

The selection is stored on codex_products.in_pilot so every candidate model
sees the same products. Nothing here applies or exports anything.
"""

import csv
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models.classification import ClassificationResult, ClassificationRun, CodexProduct

# All currently `adventure` on Codex and plainly not adventures (spec §6).
KNOWN_WRONG_SLUGS: tuple[str, ...] = (
    "d30-collection-of-height-weight-table-english",
    "d30-human-height-weight-table-english",
    "d30-npc-background-generator",
    "d30-quick-npc-personality-generator",
    "generic-spell-effect-cards",
)

DEFAULT_WEIGHTS = {"other": 2.0, "adventure": 1.5}


def _allocate(sizes: dict[str, int], quota: int, floor: int,
              weights: dict[str, float]) -> dict[str, int]:
    """Per-type counts: a floor each, then the rest proportional to size × weight."""
    alloc = {t: min(floor, s) for t, s in sizes.items()}
    remaining = max(0, quota - sum(alloc.values()))
    while remaining > 0:
        room = {t: sizes[t] - alloc[t] for t in sizes if sizes[t] > alloc[t]}
        if not room:
            break
        share = {t: sizes[t] * weights.get(t, 1.0) for t in room}
        total = sum(share.values())
        exact = {t: remaining * share[t] / total for t in room}
        given = {t: min(room[t], int(exact[t])) for t in room}
        if not any(given.values()):
            # Largest remainder gets the next single slot.
            given = {max(room, key=lambda t: (exact[t], t)): 1}
        for t, k in given.items():
            alloc[t] += k
            remaining -= k
    return alloc


async def select_pilot(
    db: AsyncSession,
    n: int = 150,
    seed: int = 20261025,
    description_share: int = 15,
    floor: int = 5,
    weights: dict[str, float] | None = None,
) -> list[str]:
    weights = DEFAULT_WEIGHTS if weights is None else weights
    rng = random.Random(seed)
    rows = list((await db.execute(select(CodexProduct).order_by(CodexProduct.slug))).scalars())

    chosen = [r for r in rows if r.slug in KNOWN_WRONG_SLUGS]
    taken = {r.slug for r in chosen}

    descriptions = [r for r in rows if r.match_method == "none" and r.slug not in taken]
    picked = rng.sample(descriptions, min(description_share, len(descriptions), n - len(chosen)))
    chosen += picked
    taken |= {r.slug for r in picked}

    by_type: dict[str, list[CodexProduct]] = defaultdict(list)
    for r in rows:
        if r.match_method != "none" and r.slug not in taken:
            by_type[r.product_type or ""].append(r)
    alloc = _allocate({t: len(g) for t, g in by_type.items()}, n - len(chosen), floor, weights)
    for t in sorted(by_type):
        chosen += rng.sample(by_type[t], alloc[t])

    slugs = sorted(r.slug for r in chosen)
    await db.execute(update(CodexProduct).values(in_pilot=False))
    await db.execute(update(CodexProduct).where(CodexProduct.slug.in_(slugs)).values(in_pilot=True))
    await db.flush()
    db.expire_all()
    return slugs


async def _run(db: AsyncSession, name: str) -> ClassificationRun | None:
    return (await db.execute(select(ClassificationRun).where(ClassificationRun.name == name))).scalar()


async def _results(db: AsyncSession, run: ClassificationRun | None) -> dict[str, ClassificationResult]:
    if run is None:
        return {}
    rows = (await db.execute(
        select(ClassificationResult).where(ClassificationResult.run_id == run.id)
    )).scalars()
    return {r.codex_product_id: r for r in rows}


def _cell(value) -> str:
    return "" if value is None else str(value)


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def _text_cell(value) -> str:
    """A display-only cell: Excel would run a leading = + - @ as a formula, and
    evidence quotes from books often start with "- " bullets."""
    text = _cell(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def _excerpt_path(excerpt_dir: Path, slug: str) -> Path:
    return excerpt_dir / f"{_UNSAFE_FILENAME.sub('_', slug).lstrip('.')}.md"


async def write_pilot_sheet(db: AsyncSession, run_names: list[str], out: Path,
                            excerpt_dir: Path) -> int:
    from grimoire.services.classification.batch import build_items

    excerpts = {i.codex_product_id: i.excerpt for i in await build_items(db, pilot=True)}
    results = {name: await _results(db, await _run(db, name)) for name in run_names}
    pilot = (await db.execute(
        select(CodexProduct).where(CodexProduct.in_pilot.is_(True)).order_by(CodexProduct.slug)
    )).scalars()

    header = ["slug", "title", "publisher", "excerpt_path", "codex_type", "codex_min", "codex_max"]
    for name in run_names:
        header += [f"{name}_{c}" for c in
                   ("type", "min", "max", "confidence", "type_evidence", "level_evidence")]
    header += ["true_type", "true_min", "true_max"]

    excerpt_dir.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    # utf-8-sig so Excel opens the sheet with the right encoding.
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for cp in pilot:
            path = _excerpt_path(excerpt_dir, cp.slug)
            path.write_text(excerpts[cp.id].text, encoding="utf-8")
            # The slug stays raw: pilot-score reads it back to find the product.
            row = [cp.slug, _text_cell(cp.title), _text_cell(cp.publisher), str(path),
                   cp.product_type or "", _cell(cp.level_range_min), _cell(cp.level_range_max)]
            for name in run_names:
                r = results[name].get(cp.id)
                row += ["", "", "", "", "", ""] if r is None else [
                    _cell(r.product_type_new), _cell(r.level_min_new), _cell(r.level_max_new),
                    _cell(r.confidence), _text_cell(r.type_evidence), _text_cell(r.level_evidence),
                ]
            writer.writerow(row + ["", "", ""])
            count += 1
    return count


@dataclass
class Score:
    run: str
    n: int
    type_accuracy: float
    level_exact: float
    level_false_positive: float
    cost_per_product: float


def _range(min_: int | None, max_: int | None) -> tuple[int | None, int | None]:
    # A half range or an inverted one is no range (spec §5).
    if min_ is not None and max_ is not None and min_ <= max_:
        return min_, max_
    return None, None


def _int(cell: str) -> int | None:
    cell = (cell or "").strip()
    return int(cell) if cell else None


async def score_pilot(db: AsyncSession, run_names: list[str], truth: Path) -> list[Score]:
    with open(truth, encoding="utf-8-sig", newline="") as f:
        labelled = [r for r in csv.DictReader(f) if (r.get("true_type") or "").strip()]
    slug_to_id = dict((await db.execute(select(CodexProduct.slug, CodexProduct.id))).all())

    scores = []
    for name in run_names:
        run = await _run(db, name)
        results = await _results(db, run)
        type_ok = level_ok = null_truths = false_pos = 0
        for row in labelled:
            r = results.get(slug_to_id.get(row["slug"]))
            truth_range = _range(_int(row["true_min"]), _int(row["true_max"]))
            got_type = r.product_type_new if r and not r.error else None
            got_range = _range(r.level_min_new, r.level_max_new) if r and not r.error else (None, None)
            type_ok += got_type == row["true_type"].strip()
            level_ok += got_range == truth_range
            if truth_range == (None, None):
                null_truths += 1
                false_pos += got_range != (None, None)
        n = len(labelled)
        per = run.cost_usd / run.request_count if run and run.request_count else 0.0
        scores.append(Score(
            run=name,
            n=n,
            type_accuracy=type_ok / n if n else 0.0,
            level_exact=level_ok / n if n else 0.0,
            level_false_positive=false_pos / null_truths if null_truths else 0.0,
            cost_per_product=per,
        ))
    return scores
