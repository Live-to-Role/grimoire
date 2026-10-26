import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from grimoire.models import ClassificationResult, ClassificationRun, CodexProduct, Product, Setting
from grimoire.services.classification.batch import (
    anthropic_api_key,
    build_items,
    collect_run,
    cost_usd,
    submit_run,
)
from grimoire.services.classification.excerpt import Excerpt
from grimoire.services.classification.batch import RunItem

CX1 = "00000000-0000-0000-0000-000000000001"
CX2 = "00000000-0000-0000-0000-000000000002"
CX3 = "00000000-0000-0000-0000-000000000003"


class FakeBatches:
    def __init__(self):
        self.created: list[SimpleNamespace] = []
        self.status: dict[str, str] = {}
        self.result_sets: dict[str, list] = {}

    def create(self, requests):
        batch_id = f"msgbatch_{len(self.created) + 1}"
        self.created.append(SimpleNamespace(id=batch_id, requests=list(requests)))
        self.status[batch_id] = "in_progress"
        return SimpleNamespace(id=batch_id, processing_status="in_progress")

    def retrieve(self, batch_id):
        return SimpleNamespace(
            id=batch_id,
            processing_status=self.status[batch_id],
            request_counts=SimpleNamespace(processing=0 if self.status[batch_id] == "ended" else 1),
        )

    def results(self, batch_id):
        return iter(self.result_sets.get(batch_id, []))


@pytest.fixture
def fake_client():
    return SimpleNamespace(messages=SimpleNamespace(batches=FakeBatches()))


def _usage(inp=1000, out=200, cache_write=0, cache_read=0):
    return SimpleNamespace(
        input_tokens=inp, output_tokens=out,
        cache_creation_input_tokens=cache_write, cache_read_input_tokens=cache_read,
    )


def _succeeded(custom_id, text, stop_reason="end_turn", usage=None):
    message = SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=usage or _usage(),
    )
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type="succeeded", message=message))


def _good(level_min=0, level_max=0, product_type="adventure"):
    return json.dumps({
        "product_type": product_type, "level_range_min": level_min, "level_range_max": level_max,
        "confidence": 0.8, "type_evidence": "an adventure", "level_evidence": "0-level funnel",
        "notes": "",
    })


def _item(cx_id, product_id=None, source="pdf"):
    return RunItem(cx_id, product_id, source, Excerpt(f"excerpt {cx_id}", source, 0, False, 3))


async def _seed(db):
    product = Product(
        file_path=r"D:\Drivethrurpg\P\T\t.pdf", file_name="t.pdf", file_size=1, file_hash="h",
        level_range_min=3, level_range_max=5,
    )
    db.add(product)
    await db.flush()
    # A pre-branch free-text type: a Core update skips the model's validator.
    await db.execute(update(Product).where(Product.id == product.id).values(product_type="Supplement"))
    await db.refresh(product)
    db.add_all([
        CodexProduct(id=CX1, slug="a", title="A", product_type="other",
                     grimoire_product_id=product.id, match_method="folder"),
        CodexProduct(id=CX2, slug="b", title="B", product_type="adventure",
                     level_range_min=1, level_range_max=2, description="blurb"),
        CodexProduct(id=CX3, slug="c", title="C", product_type="tools"),
    ])
    await db.flush()
    return product


def test_cost_usd_uses_batch_prices():
    assert cost_usd("claude-opus-5-5", 1_000_000, 100_000) == pytest.approx(3.0)
    assert cost_usd("claude-sonnet-5-5", 1_000_000, 100_000) == pytest.approx(1.5)


async def test_api_key_prefers_settings_json(db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    db.add(Setting(key="anthropic_api_key", value=json.dumps("db-key")))
    await db.flush()
    assert await anthropic_api_key(db) == "db-key"


async def test_api_key_falls_back_to_env_then_raises(db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert await anthropic_api_key(db) == "env-key"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(RuntimeError):
        await anthropic_api_key(db)


async def test_submit_creates_run_and_result_rows_with_old_values(db, fake_client):
    product = await _seed(db)
    items = [_item(CX1, product.id), _item(CX2, None, "description")]

    run = await submit_run(db, fake_client, "pilot-x", "claude-sonnet-5-5", "medium", items)

    created = fake_client.messages.batches.created
    assert len(created) == 1 and created[0].requests[0]["custom_id"] == CX1
    assert created[0].requests[1]["params"]["messages"][0]["content"] == f"excerpt {CX2}"
    assert run.status == "submitted" and run.batch_id == "msgbatch_1" and run.request_count == 2
    rows = {r.codex_product_id: r for r in (await db.execute(select(ClassificationResult))).scalars()}
    assert (rows[CX1].product_type_old, rows[CX1].level_min_old, rows[CX1].level_max_old) == ("Supplement", 3, 5)
    assert rows[CX1].product_id == product.id and rows[CX1].source == "pdf"
    # Description-only rows take their old values from Codex.
    assert (rows[CX2].product_type_old, rows[CX2].level_min_old) == ("adventure", 1)
    assert rows[CX2].product_id is None and rows[CX2].source == "description"


async def test_submit_refuses_an_existing_run_name(db, fake_client):
    await _seed(db)
    await submit_run(db, fake_client, "dup", "claude-sonnet-5-5", "medium", [_item(CX3)])
    with pytest.raises(ValueError):
        await submit_run(db, fake_client, "dup", "claude-sonnet-5-5", "medium", [_item(CX3)])


async def test_submit_chunks_large_runs(db, fake_client, monkeypatch):
    import grimoire.services.classification.batch as batch

    await _seed(db)
    monkeypatch.setattr(batch, "MAX_BATCH_REQUESTS", 2)
    run = await submit_run(db, fake_client, "big", "claude-sonnet-5-5", "medium",
                           [_item(CX1), _item(CX2), _item(CX3)])
    assert run.batch_id == "msgbatch_1,msgbatch_2"
    assert [len(b.requests) for b in fake_client.messages.batches.created] == [2, 1]


async def test_collect_returns_pending_without_wait(db, fake_client):
    await _seed(db)
    await submit_run(db, fake_client, "r", "claude-sonnet-5-5", "medium", [_item(CX1)])
    assert await collect_run(db, fake_client, "r") == {"pending": 1}


async def test_collect_stores_parsed_output_and_cost(db, fake_client):
    await _seed(db)
    await submit_run(db, fake_client, "r", "claude-sonnet-5-5", "medium", [_item(CX1)])
    batches = fake_client.messages.batches
    batches.status["msgbatch_1"] = "ended"
    batches.result_sets["msgbatch_1"] = [
        _succeeded(CX1, _good(), usage=_usage(inp=100, out=300, cache_write=50, cache_read=850))
    ]

    counts = await collect_run(db, fake_client, "r")

    assert counts == {"stored": 1, "error": 0}
    row = (await db.execute(select(ClassificationResult))).scalar_one()
    assert (row.product_type_new, row.level_min_new, row.level_max_new) == ("adventure", 0, 0)
    assert row.confidence == 0.8 and row.level_evidence == "0-level funnel" and row.error is None
    assert json.loads(row.raw_response)["product_type"] == "adventure"
    run = (await db.execute(select(ClassificationRun))).scalar_one()
    assert (run.input_tokens, run.output_tokens) == (1000, 300)
    assert run.cost_usd == pytest.approx(cost_usd("claude-sonnet-5-5", 1000, 300))
    assert run.status == "collected" and run.completed_at is not None


async def test_collect_twice_does_not_double_count_tokens(db, fake_client):
    await _seed(db)
    await submit_run(db, fake_client, "r", "claude-sonnet-5-5", "medium", [_item(CX1)])
    batches = fake_client.messages.batches
    batches.status["msgbatch_1"] = "ended"
    batches.result_sets["msgbatch_1"] = [_succeeded(CX1, _good())]
    await collect_run(db, fake_client, "r")
    await collect_run(db, fake_client, "r")
    run = (await db.execute(select(ClassificationRun))).scalar_one()
    assert (run.input_tokens, run.output_tokens) == (1000, 200)


async def test_collect_records_bad_json_and_max_tokens_as_errors(db, fake_client):
    await _seed(db)
    await submit_run(db, fake_client, "r", "claude-sonnet-5-5", "medium",
                     [_item(CX1), _item(CX2), _item(CX3)])
    batches = fake_client.messages.batches
    batches.status["msgbatch_1"] = "ended"
    batches.result_sets["msgbatch_1"] = [
        _succeeded(CX3, '{"product_type": "advent'),  # results arrive in any order
        _succeeded(CX1, _good()),
        _succeeded(CX2, _good(), stop_reason="max_tokens"),
    ]

    counts = await collect_run(db, fake_client, "r")

    assert counts == {"stored": 1, "error": 2}
    rows = {r.codex_product_id: r for r in (await db.execute(select(ClassificationResult))).scalars()}
    assert rows[CX1].error is None and rows[CX1].product_type_new == "adventure"
    assert "max_tokens" in rows[CX2].error and rows[CX2].product_type_new is None
    assert rows[CX3].error and rows[CX3].raw_response == '{"product_type": "advent'


async def test_collect_records_refusal_and_errored_results(db, fake_client):
    await _seed(db)
    await submit_run(db, fake_client, "r", "claude-sonnet-5-5", "medium", [_item(CX1), _item(CX2)])
    batches = fake_client.messages.batches
    batches.status["msgbatch_1"] = "ended"
    errored = SimpleNamespace(
        custom_id=CX2,
        result=SimpleNamespace(type="errored", error=SimpleNamespace(
            error=SimpleNamespace(type="overloaded_error", message="busy"))),
    )
    batches.result_sets["msgbatch_1"] = [_succeeded(CX1, "", stop_reason="refusal"), errored]

    assert await collect_run(db, fake_client, "r") == {"stored": 0, "error": 2}
    rows = {r.codex_product_id: r for r in (await db.execute(select(ClassificationResult))).scalars()}
    assert "refusal" in rows[CX1].error and "overloaded_error" in rows[CX2].error


async def test_build_items_uses_pdf_excerpt_or_description(db, tmp_path):
    product = await _seed(db)
    text = tmp_path / "1.json"
    text.write_text(json.dumps({"pages": [{"page": 1, "markdown": "An adventure for levels 1-3"}]}))
    product.extracted_text_path = str(text)
    product.text_extracted = True
    product.page_count = 1
    (await db.get(CodexProduct, CX1)).in_pilot = True
    (await db.get(CodexProduct, CX2)).in_pilot = True
    await db.flush()

    items = {i.codex_product_id: i for i in await build_items(db, pilot=True)}

    assert set(items) == {CX1, CX2}
    pdf = items[CX1]
    assert pdf.source == "pdf" and pdf.product_id == product.id
    for needle in ("filename: t.pdf", "publisher_folder: P", "product_folder: T", "codex_title: A",
                   "grimoire_type: Supplement", "grimoire_levels: 3-5", "levels 1-3"):
        assert needle in pdf.excerpt.text
    desc = items[CX2]
    assert desc.source == "description" and desc.product_id is None and "blurb" in desc.excerpt.text


async def test_build_items_matched_without_text_falls_back_to_description(db):
    product = await _seed(db)
    items = await build_items(db, slugs=["a"])
    assert len(items) == 1
    assert items[0].source == "description" and items[0].product_id == product.id


async def test_build_items_all(db):
    await _seed(db)
    assert len(await build_items(db, all_=True)) == 3
