import csv
from collections import Counter

import pytest
from sqlalchemy import select

from grimoire.models import ClassificationResult, ClassificationRun, CodexProduct
from grimoire.services.classification.pilot import (
    KNOWN_WRONG_SLUGS,
    score_pilot,
    select_pilot,
    write_pilot_sheet,
)

# Matched rows per current Codex type; "zine" has fewer than the floor.
TYPE_SIZES = {"other": 300, "adventure": 200, "supplement": 60, "tools": 40, "map": 12, "zine": 3}


async def _seed_snapshot(db):
    rows, n = [], 0
    for ptype, size in TYPE_SIZES.items():
        for _ in range(size):
            n += 1
            rows.append(CodexProduct(id=f"id-{n:05d}", slug=f"{ptype}-{n:05d}", title=f"T{n}",
                                     product_type=ptype, match_method="folder"))
    for i in range(40):
        rows.append(CodexProduct(id=f"desc-{i:03d}", slug=f"desc-{i:03d}", title=f"D{i}",
                                 product_type="other", match_method="none", description="blurb"))
    for slug in KNOWN_WRONG_SLUGS:
        rows.append(CodexProduct(id=f"kw-{slug}"[:36], slug=slug, title=slug,
                                 product_type="adventure", match_method="folder"))
    db.add_all(rows)
    await db.flush()


async def _pilot_rows(db):
    return list((await db.execute(select(CodexProduct).where(CodexProduct.in_pilot.is_(True)))).scalars())


async def test_select_pilot_includes_known_wrong_and_respects_floor_and_share(db):
    await _seed_snapshot(db)

    slugs = await select_pilot(db)

    assert len(slugs) == 150 and len(set(slugs)) == 150
    assert set(KNOWN_WRONG_SLUGS) <= set(slugs)
    rows = await _pilot_rows(db)
    assert sorted(r.slug for r in rows) == sorted(slugs)
    assert sum(1 for r in rows if r.match_method == "none") == 15
    matched = Counter(r.product_type for r in rows if r.match_method != "none")
    for ptype, size in TYPE_SIZES.items():
        assert matched[ptype] >= min(5, size), ptype
    # other and adventure are weighted up beyond their proportional share.
    assert matched["other"] > matched["adventure"] > matched["supplement"]


async def test_select_pilot_is_reproducible_and_resets_previous_selection(db):
    await _seed_snapshot(db)
    first = await select_pilot(db)
    second = await select_pilot(db)
    assert first == second
    other = await select_pilot(db, seed=1)
    assert other != first
    assert sorted(r.slug for r in await _pilot_rows(db)) == sorted(other)


async def test_select_pilot_skips_known_slugs_missing_from_snapshot(db):
    db.add_all([CodexProduct(id=f"i{i}", slug=f"s{i}", title="t", product_type="adventure",
                             match_method="folder") for i in range(20)])
    await db.flush()
    slugs = await select_pilot(db, n=10, description_share=0)
    assert len(slugs) == 10 and not set(KNOWN_WRONG_SLUGS) & set(slugs)


async def _seed_scored(db, truth_rows):
    """Four pilot products, two runs; returns truth CSV rows keyed by slug."""
    run_a = ClassificationRun(name="a", model="claude-sonnet-5-5", effort="medium",
                              request_count=4, cost_usd=0.04, status="collected")
    run_b = ClassificationRun(name="b", model="claude-opus-5-5", effort="medium",
                              request_count=4, cost_usd=0.08, status="collected")
    db.add_all([run_a, run_b])
    await db.flush()
    for slug, (ptype, lo, hi) in truth_rows.items():
        db.add(CodexProduct(id=slug, slug=slug, title=slug.upper(), publisher="Pub",
                            product_type="other", match_method="none", in_pilot=True,
                            description=f"about {slug}"))
    await db.flush()
    return run_a, run_b


async def test_pilot_sheet_columns_per_run(db, tmp_path):
    run_a, run_b = await _seed_scored(db, {"p1": (None, None, None), "p2": (None, None, None)})
    db.add(ClassificationResult(run_id=run_a.id, codex_product_id="p1", source="description",
                                product_type_new="adventure", level_min_new=0, level_max_new=0,
                                confidence=0.9, type_evidence="te", level_evidence="le"))
    await db.flush()

    out = tmp_path / "pilot.csv"
    n = await write_pilot_sheet(db, ["a", "b"], out, tmp_path / "excerpts")

    assert n == 2
    with open(out, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        rows = {r["slug"]: r for r in reader}
    assert header[:7] == ["slug", "title", "publisher", "excerpt_path", "codex_type", "codex_min", "codex_max"]
    assert header[7:13] == ["a_type", "a_min", "a_max", "a_confidence", "a_type_evidence", "a_level_evidence"]
    assert header[13:19] == ["b_type", "b_min", "b_max", "b_confidence", "b_type_evidence", "b_level_evidence"]
    assert header[-3:] == ["true_type", "true_min", "true_max"]
    assert (rows["p1"]["a_type"], rows["p1"]["a_min"], rows["p1"]["a_max"]) == ("adventure", "0", "0")
    assert rows["p1"]["b_type"] == "" and rows["p1"]["true_type"] == ""
    excerpt = tmp_path / "excerpts" / "p1.md"
    assert rows["p1"]["excerpt_path"] == str(excerpt)
    assert "about p1" in excerpt.read_text(encoding="utf-8")


def _write_truth(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["slug", "a_type", "true_type", "true_min", "true_max"])
        for slug, (ptype, lo, hi) in rows.items():
            w.writerow([slug, "ignored", ptype or "", "" if lo is None else lo, "" if hi is None else hi])


async def test_score_pilot_computes_accuracy_and_level_fp(db, tmp_path):
    truth = {
        "p1": ("adventure", 1, 3),   # model: adventure 1-3  -> type ok, levels exact
        "p2": ("adventure", 0, 0),   # model: adventure 1-1  -> type ok, levels wrong
        "p3": ("tools", None, None),  # model: tools null     -> type ok, correctly null
        "p4": ("map", None, None),    # model: supplement 2-4 -> type wrong, level false positive
        "p5": (None, None, None),     # unlabelled: skipped
    }
    run_a, _ = await _seed_scored(db, truth)
    model = {"p1": ("adventure", 1, 3), "p2": ("adventure", 1, 1),
             "p3": ("tools", None, None), "p4": ("supplement", 2, 4), "p5": ("map", None, None)}
    for slug, (ptype, lo, hi) in model.items():
        db.add(ClassificationResult(run_id=run_a.id, codex_product_id=slug, source="description",
                                    product_type_new=ptype, level_min_new=lo, level_max_new=hi))
    await db.flush()
    path = tmp_path / "truth.csv"
    _write_truth(path, truth)

    scores = {s.run: s for s in await score_pilot(db, ["a", "b"], path)}

    a = scores["a"]
    assert a.n == 4
    assert a.type_accuracy == pytest.approx(0.75)
    assert a.level_exact == pytest.approx(0.5)
    assert a.level_false_positive == pytest.approx(0.5)
    assert a.cost_per_product == pytest.approx(0.01)
    # Run b has no results: every labelled product counts as wrong.
    assert scores["b"].n == 4 and scores["b"].type_accuracy == 0.0


async def test_score_pilot_treats_half_ranges_as_no_range(db, tmp_path):
    truth = {"p1": ("adventure", None, None)}
    run_a, _ = await _seed_scored(db, truth)
    db.add(ClassificationResult(run_id=run_a.id, codex_product_id="p1", source="description",
                                product_type_new="adventure", level_min_new=3, level_max_new=None))
    await db.flush()
    path = tmp_path / "truth.csv"
    _write_truth(path, truth)
    a = (await score_pilot(db, ["a"], path))[0]
    assert a.level_exact == 1.0 and a.level_false_positive == 0.0
