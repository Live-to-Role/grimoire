import pytest

from grimoire.models import ClassificationResult, ClassificationRun, CodexProduct, Product
from grimoire.services.classification.apply import apply_run, effective_levels

CX1 = "00000000-0000-0000-0000-000000000001"
CX2 = "00000000-0000-0000-0000-000000000002"


async def _product(db, name, product_type="Supplement", levels=(None, None)):
    p = Product(file_path=f"/lib/Pub/Folder/{name}", file_name=name, file_size=1,
                file_hash=name, product_type=product_type,
                level_range_min=levels[0], level_range_max=levels[1])
    db.add(p)
    await db.flush()
    return p


async def _run(db, *results):
    run = ClassificationRun(name="full", model="claude-sonnet-5-5", effort="medium",
                            status="collected")
    db.add(run)
    await db.flush()
    for i, fields in enumerate(results):
        cx = CX1 if i == 0 else CX2
        db.add(CodexProduct(id=cx, slug=f"slug-{i}", title=f"T{i}"))
        db.add(ClassificationResult(run_id=run.id, codex_product_id=cx,
                                    **{"source": "pdf", **fields}))
    await db.flush()
    return run


async def test_apply_overwrites_type_and_replaces_levels(db):
    p = await _product(db, "a.pdf", "Supplement", (3, 5))
    await _run(db, dict(product_id=p.id, product_type_new="adventure",
                        level_min_new=1, level_max_new=3))

    report = await apply_run(db, "full")

    await db.refresh(p)
    assert (p.product_type, p.level_range_min, p.level_range_max) == ("adventure", 1, 3)
    assert report.applied == 1


async def test_apply_writes_level_zero(db):
    p = await _product(db, "a.pdf", "adventure", (1, 1))
    await _run(db, dict(product_id=p.id, product_type_new="adventure",
                        level_min_new=0, level_max_new=0))

    await apply_run(db, "full")

    await db.refresh(p)
    assert (p.level_range_min, p.level_range_max) == (0, 0)


async def test_apply_null_levels_keep_existing(db):
    p = await _product(db, "a.pdf", "Supplement", (3, 5))
    await _run(db, dict(product_id=p.id, product_type_new="gm_tools",
                        level_min_new=None, level_max_new=None))

    await apply_run(db, "full")

    await db.refresh(p)
    assert (p.product_type, p.level_range_min, p.level_range_max) == ("gm_tools", 3, 5)


async def test_half_range_and_inverted_range_are_no_range():
    assert effective_levels(3, None) == (None, None)
    assert effective_levels(5, 3) == (None, None)
    assert effective_levels(0, 2) == (0, 2)


async def test_apply_half_range_keeps_existing(db):
    p = await _product(db, "a.pdf", "adventure", (3, 5))
    await _run(db, dict(product_id=p.id, product_type_new="adventure",
                        level_min_new=7, level_max_new=None))

    await apply_run(db, "full")

    await db.refresh(p)
    assert (p.level_range_min, p.level_range_max) == (3, 5)


async def test_apply_skips_errors_and_is_idempotent(db):
    ok = await _product(db, "ok.pdf", "Supplement")
    bad = await _product(db, "bad.pdf", "Supplement")
    await _run(db,
               dict(product_id=ok.id, product_type_new="bestiary"),
               dict(product_id=bad.id, error="max_tokens"))

    first = await apply_run(db, "full")
    ok.product_type = "edited by hand"
    await db.commit()
    second = await apply_run(db, "full")

    await db.refresh(ok)
    await db.refresh(bad)
    assert (first.applied, first.skipped_error) == (1, 1)
    assert (second.applied, second.skipped_applied, second.skipped_error) == (0, 1, 1)
    assert ok.product_type == "edited by hand"
    assert bad.product_type == "Supplement"


async def test_apply_counts_results_without_product(db):
    await _run(db, dict(product_id=None, product_type_new="adventure", source="description"))

    report = await apply_run(db, "full")

    assert (report.applied, report.skipped_no_product) == (0, 1)


async def test_apply_leaves_sibling_untouched(db):
    matched = await _product(db, "main.pdf", "Supplement", (2, 4))
    sibling = await _product(db, "main-printer-friendly.pdf", "Supplement", (2, 4))
    await _run(db, dict(product_id=matched.id, product_type_new="adventure",
                        level_min_new=5, level_max_new=7))

    await apply_run(db, "full")

    await db.refresh(sibling)
    assert (sibling.product_type, sibling.level_range_min, sibling.level_range_max) == (
        "Supplement", 2, 4)


async def test_apply_unknown_run_raises(db):
    with pytest.raises(ValueError):
        await apply_run(db, "nope")


async def test_apply_refuses_uncollected_run(db):
    # submit_run creates result rows before the batch ends; their new type is null.
    p = await _product(db, "a.pdf", "Supplement")
    run = await _run(db, dict(product_id=p.id, product_type_new=None))
    run.status = "submitted"

    with pytest.raises(ValueError, match="collected"):
        await apply_run(db, "full")

    await db.refresh(p)
    assert p.product_type == "Supplement"
