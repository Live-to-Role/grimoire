"""Write a collected run's decisions onto Grimoire products.

Only the matched product changes: siblings in the same folder (printer-friendly
copies, other editions) were never classified and are left alone. A result is
applied once; applied_at marks it so a re-run never overwrites a hand edit.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Product
from grimoire.models.classification import ClassificationResult, ClassificationRun


def effective_levels(min_: int | None, max_: int | None) -> tuple[int | None, int | None]:
    """A half range or an inverted one is no range (spec §5)."""
    if min_ is not None and max_ is not None and min_ <= max_:
        return min_, max_
    return None, None


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
