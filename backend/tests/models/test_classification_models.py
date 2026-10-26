from grimoire.models import ClassificationResult, ClassificationRun, CodexProduct


async def test_tables_exist_and_roundtrip(db):
    cp = CodexProduct(id="0f1e2d3c-0000-0000-0000-000000000001", slug="x", title="X")
    run = ClassificationRun(name="t", model="claude-sonnet-5-5", effort="medium")
    db.add_all([cp, run])
    await db.flush()
    r = ClassificationResult(run_id=run.id, codex_product_id=cp.id, source="pdf", level_min_new=0)
    db.add(r)
    await db.flush()
    assert cp.match_method == "none" and cp.in_pilot is False
    assert run.status == "created"
    # Level 0 is a real value (DCC funnels) and must survive storage.
    assert r.level_min_new == 0
