"""Diagnostics must account for files that were scanned but skipped.

"39 PDFs on disk, one product in the library" is invisible in every other
number the report shows: the queue is healthy, the worker is running, the
folder is readable. The files were dropped by an exclusion rule, and nothing
tied the missing count to the rule responsible.
"""
from grimoire.api.routes.health import get_diagnostics_data
from grimoire.models import ExclusionRule, Product, Setting, WatchedFolder
from grimoire.services.queue_processor import PROCESSING_PAUSED_KEY, WORKER_HEARTBEAT_KEY


async def _healthy_worker(db):
    from datetime import UTC, datetime

    db.add(Setting(key=WORKER_HEARTBEAT_KEY, value=datetime.now(UTC).isoformat()))
    db.add(Setting(key=PROCESSING_PAUSED_KEY, value="false"))
    db.add(WatchedFolder(path="/tmp", label="tmp", enabled=True))
    await db.flush()


async def _diag(db):
    return await get_diagnostics_data(db, check_network=False)


async def test_rules_that_excluded_nothing_are_omitted(db):
    await _healthy_worker(db)
    db.add(ExclusionRule(rule_type="filename", pattern="*.tmp", files_excluded=0))
    await db.flush()

    data = await _diag(db)
    assert data["library"]["exclusions"] == []


async def test_rule_that_excluded_files_is_reported(db):
    await _healthy_worker(db)
    db.add(ExclusionRule(
        rule_type="size_min",
        pattern="10240",
        description="Files under 10KB (likely corrupt)",
        files_excluded=38,
    ))
    await db.flush()

    data = await _diag(db)
    exclusions = data["library"]["exclusions"]
    assert len(exclusions) == 1
    assert exclusions[0]["files_excluded"] == 38
    assert exclusions[0]["pattern"] == "10240"
    assert "10KB" in exclusions[0]["description"]


async def test_exclusions_are_ranked_by_impact(db):
    await _healthy_worker(db)
    db.add(ExclusionRule(rule_type="filename", pattern="*.tmp", files_excluded=2))
    db.add(ExclusionRule(rule_type="size_min", pattern="10240", files_excluded=38))
    await db.flush()

    data = await _diag(db)
    counts = [e["files_excluded"] for e in data["library"]["exclusions"]]
    assert counts == sorted(counts, reverse=True)


async def test_exclusions_outnumbering_the_library_is_a_problem(db):
    """38 skipped against 1 product is the reported symptom."""
    await _healthy_worker(db)
    db.add(Product(file_name="a.pdf", file_path="/tmp/a.pdf", file_size=50000, file_hash="h"))
    db.add(ExclusionRule(
        rule_type="size_min",
        pattern="10240",
        description="Files under 10KB (likely corrupt)",
        files_excluded=38,
    ))
    await db.flush()

    data = await _diag(db)
    problems = {p["code"]: p for p in data["problems"]}
    assert "files_excluded_by_rules" in problems
    problem = problems["files_excluded_by_rules"]
    assert "38" in problem["message"]
    # Must name the rule responsible, not just the total.
    assert "10240" in problem["message"] or "10KB" in problem["message"]
    assert "Exclusions" in problem["hint"]


async def test_a_few_exclusions_in_a_healthy_library_is_not_a_problem(db):
    await _healthy_worker(db)
    for i in range(50):
        db.add(Product(
            file_name=f"{i}.pdf", file_path=f"/tmp/{i}.pdf", file_size=50000, file_hash=f"h{i}"
        ))
    db.add(ExclusionRule(rule_type="filename", pattern="*.tmp", files_excluded=3))
    await db.flush()

    data = await _diag(db)
    assert "files_excluded_by_rules" not in {p["code"] for p in data["problems"]}


async def test_disabled_rules_are_marked_as_such(db):
    await _healthy_worker(db)
    db.add(ExclusionRule(
        rule_type="size_min", pattern="10240", files_excluded=38, enabled=False
    ))
    await db.flush()

    data = await _diag(db)
    assert data["library"]["exclusions"][0]["enabled"] is False
