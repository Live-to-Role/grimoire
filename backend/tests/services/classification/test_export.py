import json

import httpx
import pytest

from grimoire.models import ClassificationResult, ClassificationRun, CodexProduct, Product, Setting
from grimoire.services.classification.export import (
    ExportItem,
    build_items,
    codex_token,
    read_reviewed,
    send_items,
    write_report,
)


def _cx(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


async def _run(db, rows, status="collected"):
    """rows: (codex type, codex min, codex max, result fields) per Codex product."""
    run = ClassificationRun(name="full", model="claude-sonnet-5-5", effort="medium", status=status)
    db.add(run)
    await db.flush()
    for i, (ctype, cmin, cmax, fields) in enumerate(rows, start=1):
        db.add(CodexProduct(id=_cx(i), slug=f"slug-{i}", title=f"Title {i}", product_type=ctype,
                            level_range_min=cmin, level_range_max=cmax))
        db.add(ClassificationResult(run_id=run.id, codex_product_id=_cx(i),
                                    **{"source": "pdf", "confidence": 0.9, **fields}))
    await db.flush()
    return run


def _by_slug(items):
    return {i.slug: i for i in items}


async def test_build_items_only_differences_and_fill_vs_correction(db):
    await _run(db, [
        ("other", None, None, dict(product_type_new="adventure")),
        ("adventure", None, None, dict(product_type_new="tools")),
        ("bestiary", 1, 5, dict(product_type_new="bestiary", level_min_new=1, level_max_new=5)),
        ("adventure", None, None, dict(product_type_new="adventure", level_min_new=0,
                                       level_max_new=0)),
        ("adventure", 1, 5, dict(product_type_new="adventure", level_min_new=1, level_max_new=3)),
    ])

    items = _by_slug(await build_items(db, "full"))

    assert items["slug-1"].fields == {"product_type": "adventure"}
    assert items["slug-1"].kinds == {"product_type": "fill"}
    assert items["slug-2"].fields == {"product_type": "tools"}
    assert items["slug-2"].kinds == {"product_type": "correction"}
    assert "slug-3" not in items  # nothing differs
    assert items["slug-4"].fields == {"level_range_min": 0, "level_range_max": 0}
    assert items["slug-4"].kinds == {"level_range_min": "fill", "level_range_max": "fill"}
    assert items["slug-5"].fields == {"level_range_max": 3}
    assert items["slug-5"].kinds == {"level_range_max": "correction"}
    assert items["slug-5"].old == {"product_type": "adventure", "level_range_min": 1,
                                   "level_range_max": 5}


async def test_other_is_fill_only(db):
    await _run(db, [
        ("adventure", None, None, dict(product_type_new="other")),
        ("other", None, None, dict(product_type_new="other")),
        (None, None, None, dict(product_type_new="other")),
        ("", None, None, dict(product_type_new="other")),
    ])

    items = _by_slug(await build_items(db, "full"))

    assert "slug-1" not in items and "slug-2" not in items
    assert items["slug-3"].fields == {"product_type": "other"}
    assert items["slug-3"].kinds == {"product_type": "fill"}
    assert items["slug-4"].kinds == {"product_type": "fill"}


async def test_items_never_carry_none_or_core_rules(db):
    await _run(db, [
        ("adventure", 1, 3, dict(product_type_new=None, level_min_new=None, level_max_new=None)),
        ("other", None, None, dict(product_type_new="core_rules")),
        ("other", 2, 4, dict(product_type_new="adventure", level_min_new=5, level_max_new=None)),
        ("other", None, None, dict(product_type_new="adventure", error="max_tokens")),
    ])

    items = await build_items(db, "full")

    assert [i.slug for i in items] == ["slug-3"]
    assert items[0].fields == {"product_type": "adventure"}
    for item in items:
        assert None not in item.fields.values()
        assert "core_rules" not in item.fields.values()


async def test_min_confidence_filters(db):
    await _run(db, [
        ("other", None, None, dict(product_type_new="adventure", confidence=0.4)),
        ("other", None, None, dict(product_type_new="adventure", confidence=0.8)),
    ])

    items = await build_items(db, "full", min_confidence=0.6)

    assert [i.slug for i in items] == ["slug-2"]


async def test_build_items_flags_shared_files(db):
    db.add(Product(id=77, file_path="/l/promo.pdf", file_name="promo.pdf", file_size=1,
                   file_hash="p"))
    await _run(db, [
        ("other", None, None, dict(product_type_new="map", product_id=77)),
        ("other", None, None, dict(product_type_new="map", product_id=77)),
        ("other", None, None, dict(product_type_new="adventure")),
    ])

    items = _by_slug(await build_items(db, "full"))

    assert items["slug-1"].shared_with == 1 and items["slug-2"].shared_with == 1
    assert items["slug-3"].shared_with == 0


async def test_build_items_refuses_uncollected_run(db):
    await _run(db, [("other", None, None, dict(product_type_new=None))], status="submitted")

    with pytest.raises(ValueError, match="collected"):
        await build_items(db, "full")


async def test_codex_token_reads_json_encoded_setting(db):
    db.add(Setting(key="codex_api_key", value=json.dumps("tok-123")))
    await db.flush()

    assert await codex_token(db) == "tok-123"


def _item(n: int, **fields) -> ExportItem:
    return ExportItem(codex_id=_cx(n), slug=f"slug-{n}", title=f"Title {n}",
                      fields=fields or {"product_type": "adventure"},
                      kinds={k: "fill" for k in (fields or {"product_type": 1})},
                      confidence=0.9, type_evidence="quote", level_evidence=None)


def _codex(requests, status_for=lambda key: "changed"):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request, body))
        results = [{"key": i["id"], "status": status_for(i["id"]), "changes": {},
                    "protected": [], "errors": []} for i in body["items"]]
        return httpx.Response(200, json={"dry_run": body["dry_run"], "summary": {},
                                         "results": results})
    return httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="https://codex.test/api/v1")


def test_send_items_chunks_of_100_and_headers():
    requests = []
    items = [_item(n) for n in range(1, 251)]

    outcomes = send_items(items, "tok", dry_run=True, client=_codex(requests))

    assert [len(b["items"]) for _, b in requests] == [100, 100, 50]
    for request, body in requests:
        assert body["dry_run"] is True
        assert request.url.path == "/api/v1/classification/"
        assert request.headers["Authorization"] == "Token tok"
        assert request.headers["User-Agent"] == "Grimoire/classification"
    assert requests[0][1]["items"][0] == {"id": _cx(1), "product_type": "adventure"}
    assert len(outcomes) == 250 and outcomes[_cx(1)]["status"] == "changed"


def test_send_items_not_found_lands_in_outcomes():
    requests = []
    client = _codex(requests, status_for=lambda key: "not_found" if key == _cx(2) else "changed")

    outcomes = send_items([_item(1), _item(2)], "tok", dry_run=True, client=client)

    assert outcomes[_cx(2)]["status"] == "not_found"
    assert outcomes[_cx(1)]["status"] == "changed"


def test_send_items_raises_on_403():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"error": "no"})),
        base_url="https://codex.test/api/v1")

    with pytest.raises(httpx.HTTPStatusError):
        send_items([_item(1)], "tok", dry_run=True, client=client)


def test_report_roundtrip_respects_send_column(tmp_path):
    items = [
        _item(1, product_type="tools"),
        _item(2, level_range_min=0, level_range_max=0),
        _item(3, product_type="map", level_range_max=4),
    ]
    items[0].title = "=HYPERLINK(evil)"
    outcomes = {_cx(1): {"status": "changed", "protected": [], "errors": []},
                _cx(2): {"status": "protected", "protected": ["level_range_min"], "errors": []}}
    out = tmp_path / "report.csv"

    write_report(items, outcomes, out)
    text = out.read_text(encoding="utf-8-sig")
    assert "'=HYPERLINK(evil)" in text
    out.write_text(text.replace(f"yes,{_cx(3)}", f"No,{_cx(3)}"), encoding="utf-8-sig")
    reviewed = read_reviewed(out)

    assert [i.codex_id for i in reviewed] == [_cx(1), _cx(2)]
    assert reviewed[0].fields == {"product_type": "tools"}
    assert reviewed[1].fields == {"level_range_min": 0, "level_range_max": 0}


def test_cli_live_requires_from_and_yes(tmp_path, capsys):
    from scripts.classify import main

    reviewed = str(tmp_path / "r.csv")
    for argv, needed in (
        (["export", "--live", "--from", reviewed], "--yes"),
        (["export", "--live", "--yes"], "--from"),
        (["export", "--from", reviewed, "--yes"], "--live"),
    ):
        with pytest.raises(SystemExit):
            main(argv)
        err = capsys.readouterr().err
        # Refused by the export check itself, not by argparse not knowing "export".
        assert "invalid choice" not in err and needed in err


def test_reviewed_items_keep_old_values_kinds_and_shared_count(tmp_path):
    # The live summary is built from read_reviewed; without the old values it
    # printed every transition as "None -> ..." and every shared count as 0.
    item = ExportItem(codex_id=_cx(1), slug="slug-1", title="T", confidence=0.9,
                      fields={"product_type": "map", "level_range_min": 1, "level_range_max": 3},
                      kinds={"product_type": "correction", "level_range_min": "fill",
                             "level_range_max": "correction"},
                      type_evidence=None, level_evidence=None,
                      old={"product_type": "adventure", "level_range_min": None,
                           "level_range_max": 5},
                      shared_with=10)
    out = tmp_path / "report.csv"
    write_report([item], {}, out)

    [reviewed] = read_reviewed(out)

    assert reviewed.old == item.old
    assert reviewed.kinds == item.kinds
    assert reviewed.shared_with == 10
