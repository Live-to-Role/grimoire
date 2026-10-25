import pytest

from grimoire.models import ClassificationResult, ClassificationRun, CodexProduct, Product
from grimoire.services.classification.apply import apply_run, apply_vocab_migration, effective_levels

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


async def _vocab_rows(db):
    from sqlalchemy import select
    run = (await db.execute(
        select(ClassificationRun).where(ClassificationRun.name == "vocab-migration"))).scalar()
    if run is None:
        return run, []
    rows = (await db.execute(
        select(ClassificationResult).where(ClassificationResult.run_id == run.id))).scalars().all()
    return run, rows


async def test_vocab_migration_maps_table_values_and_records_old(db):
    p = await _product(db, "s.pdf", "Supplement")
    enum_already = await _product(db, "e.pdf", "adventure")

    counts = await apply_vocab_migration(db)

    await db.refresh(p)
    await db.refresh(enum_already)
    run, rows = await _vocab_rows(db)
    assert p.product_type == "supplement" and enum_already.product_type == "adventure"
    assert (run.model, run.effort) == ("table", "none")
    assert [(r.product_id, r.source, r.product_type_old, r.product_type_new) for r in rows] == [
        (p.id, "vocab", "Supplement", "supplement")]
    assert rows[0].applied_at is not None
    assert counts["supplement"] == 1


async def test_vocab_migration_leaves_unmapped_and_ai_applied_rows(db):
    from datetime import datetime
    anthology = await _product(db, "a.pdf", "Anthology")
    ai = await _product(db, "ai.pdf", "Supplement")
    run = ClassificationRun(name="full", model="claude-sonnet-5-5", effort="medium",
                            status="collected")
    db.add(run)
    await db.flush()
    # The AI result was applied and a person has since set a free-text type by hand.
    db.add(ClassificationResult(run_id=run.id, product_id=ai.id, source="pdf",
                                product_type_new="gm_tools", applied_at=datetime(2026, 10, 25)))
    await db.flush()

    counts = await apply_vocab_migration(db)

    await db.refresh(anthology)
    await db.refresh(ai)
    assert anthology.product_type == "Anthology" and ai.product_type == "Supplement"
    assert counts["unmapped"] == 1


async def test_vocab_migration_keeps_image_free_text_without_image_flag(db):
    # codex_eligibility refuses "Stock Art" by its free text. Mapped to "other",
    # an unflagged stock-art pack would become contributable to Codex.
    unflagged = await _product(db, "art.pdf", "Stock Art")
    flagged = await _product(db, "tok.pdf", "Token")
    flagged.is_image_content = True
    await db.flush()

    counts = await apply_vocab_migration(db)

    await db.refresh(unflagged)
    await db.refresh(flagged)
    assert unflagged.product_type == "Stock Art"
    assert flagged.product_type == "tools"
    assert counts["kept_image_type"] == 1


async def test_vocab_migration_dry_run_writes_nothing(db):
    p = await _product(db, "s.pdf", "Supplement")

    counts = await apply_vocab_migration(db, dry_run=True)

    await db.refresh(p)
    run, rows = await _vocab_rows(db)
    assert counts["supplement"] == 1
    assert p.product_type == "Supplement" and run is None and rows == []


async def test_vocab_migration_reruns_reuse_the_run(db):
    await _product(db, "s.pdf", "Supplement")
    await apply_vocab_migration(db)
    later = await _product(db, "later.pdf", "Adventure")

    counts = await apply_vocab_migration(db)

    await db.refresh(later)
    run, rows = await _vocab_rows(db)
    assert later.product_type == "adventure" and len(rows) == 2
    assert counts.get("supplement", 0) == 0
