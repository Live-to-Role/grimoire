"""Write a collected run's decisions onto Grimoire products.

Only the matched product changes: siblings in the same folder (printer-friendly
copies, other editions) were never classified and are left alone. A result is
applied once; applied_at marks it so a re-run never overwrites a hand edit.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Product
from grimoire.models.classification import ClassificationResult, ClassificationRun
from grimoire.services.classification.enum import (
    CODEX_PRODUCT_TYPES, IMAGE_PRODUCT_TYPES, normalize_free_text,
)

VOCAB_RUN = "vocab-migration"


def effective_levels(min_: int | None, max_: int | None) -> tuple[int | None, int | None]:
    """A half range or an inverted one is no range (spec §5)."""
    if min_ is not None and max_ is not None and min_ <= max_:
        return min_, max_
    return None, None


def coerce_levels(min_, max_) -> tuple[int | None, int | None]:
    """A model's level answer as a range: whole numbers 0-40, both ends, min <= max.

    Identification models answer "", "3rd" or 99 as often as a number; anything
    that is not a clean range is no range, and the stored one is left alone.
    """
    def level(value) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        return value if isinstance(value, int) and 0 <= value <= 40 else None

    return effective_levels(level(min_), level(max_))


@dataclass
class ApplyReport:
    applied: int = 0
    skipped_applied: int = 0
    skipped_error: int = 0
    skipped_no_product: int = 0


async def apply_run(db: AsyncSession, run_name: str) -> ApplyReport:
    run = (await db.execute(
        select(ClassificationRun).where(ClassificationRun.name == run_name)
    )).scalar()
    if run is None:
        raise ValueError(f"no run named {run_name!r}")
    # Rows exist from submit onward with a null new type; applying early would
    # blank every product's type.
    if run.status != "collected":
        raise ValueError(f"run {run_name!r} is {run.status}, not collected")

    results = (await db.execute(
        select(ClassificationResult).where(ClassificationResult.run_id == run.id)
    )).scalars().all()
    products = {p.id: p for p in (await db.execute(
        select(Product).where(Product.id.in_({r.product_id for r in results if r.product_id}))
    )).scalars()}

    report = ApplyReport()
    now = datetime.now(UTC).replace(tzinfo=None)
    for r in results:
        if r.error:
            report.skipped_error += 1
        elif r.applied_at is not None:
            report.skipped_applied += 1
        elif r.product_id is None or r.product_id not in products:
            report.skipped_no_product += 1
        else:
            product = products[r.product_id]
            product.product_type = r.product_type_new
            lo, hi = effective_levels(r.level_min_new, r.level_max_new)
            # A null range means the text states none, not that the old one is wrong.
            if lo is not None:
                product.level_range_min, product.level_range_max = lo, hi
            r.applied_at = now
            report.applied += 1
    await db.commit()
    return report


async def apply_vocab_migration(db: AsyncSession, dry_run: bool = False) -> dict[str, int]:
    """Map the free-text types of products no AI run reached onto the enum.

    Products with an applied result of any run are left alone: their type came
    from the model, or from a person after it. Returns counts by target value,
    plus "unmapped" and "kept_image_type".
    """
    reached = set((await db.execute(
        select(ClassificationResult.product_id).where(
            ClassificationResult.product_id.is_not(None),
            ClassificationResult.applied_at.is_not(None),
        )
    )).scalars())
    products = (await db.execute(
        select(Product).where(
            Product.product_type.is_not(None),
            Product.product_type.not_in(CODEX_PRODUCT_TYPES),
        ).order_by(Product.id)
    )).scalars().all()

    run = None
    if not dry_run:
        run = (await db.execute(
            select(ClassificationRun).where(ClassificationRun.name == VOCAB_RUN)
        )).scalar()
        if run is None:
            run = ClassificationRun(name=VOCAB_RUN, model="table", effort="none",
                                    status="collected")
            db.add(run)
            await db.flush()

    counts: Counter[str] = Counter()
    now = datetime.now(UTC).replace(tzinfo=None)
    for product in products:
        if product.id in reached:
            continue
        old = product.product_type
        new = normalize_free_text(old)
        if new is None:
            counts["unmapped"] += 1
            continue
        # codex_eligibility and the image reset recognise image collections by
        # this free text; "Stock Art" -> other would hide it from both. Same
        # rule as the Product validator.
        if old.strip().lower() in IMAGE_PRODUCT_TYPES and new != "map":
            counts["kept_image_type"] += 1
            continue
        counts[new] += 1
        if dry_run:
            continue
        db.add(ClassificationResult(
            run_id=run.id, product_id=product.id, source="vocab",
            product_type_old=old, product_type_new=new, applied_at=now,
        ))
        product.product_type = new
    if not dry_run:
        await db.commit()
    return dict(counts)


async def restore_image_types(db: AsyncSession, dry_run: bool = False) -> int:
    """Put back the image labels the vocab migration replaced ("Token" -> tools).

    Only where the product still holds the migrated value: anything changed
    since was a person's decision. The record is updated too, so it matches the
    product. Returns the number restored.
    """
    rows = (await db.execute(
        select(ClassificationResult, Product)
        .join(ClassificationRun, ClassificationResult.run_id == ClassificationRun.id)
        .join(Product, ClassificationResult.product_id == Product.id)
        .where(ClassificationRun.name == VOCAB_RUN)
    )).all()
    restored = 0
    for row, product in rows:
        old, new = row.product_type_old, row.product_type_new
        if (not old or old.strip().lower() not in IMAGE_PRODUCT_TYPES or new == "map"
                or product.product_type != new):
            continue
        restored += 1
        if dry_run:
            continue
        product.product_type = old
        row.product_type_new = old
    if not dry_run:
        await db.commit()
    return restored
