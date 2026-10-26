"""Submit classification runs to the Message Batches API and collect results.

A run never changes a product: it only fills classification_results. The
client is passed in so tests can use a fake; the CLI passes anthropic.Anthropic.
"""

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Product, Setting
from grimoire.models.classification import ClassificationResult, ClassificationRun, CodexProduct
from grimoire.services.classification.enum import normalize_free_text
from grimoire.services.classification.excerpt import (
    Excerpt,
    build_description_excerpt,
    build_excerpt,
)
from grimoire.services.classification.matching import product_folder
from grimoire.services.classification.prompt import build_request, parse_output

# Message Batches prices, $ per million tokens (half the standard rate).
BATCH_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (2.00, 10.00),
    "claude-sonnet-5-5": (1.00, 5.00),
}

MAX_BATCH_REQUESTS = 10_000


def _now() -> datetime:
    # Naive UTC, matching the CURRENT_TIMESTAMP server defaults on these columns.
    return datetime.now(UTC).replace(tzinfo=None)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = BATCH_PRICES[model]
    return input_tokens / 1_000_000 * price_in + output_tokens / 1_000_000 * price_out


async def anthropic_api_key(db: AsyncSession) -> str:
    row = await db.get(Setting, "anthropic_api_key")
    if row is not None:
        key = json.loads(row.value)
        if key:
            return key
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if key:
        return key
    raise RuntimeError("No Anthropic API key in settings or ANTHROPIC_API_KEY")


@dataclass
class RunItem:
    codex_product_id: str
    product_id: int | None
    source: str
    excerpt: Excerpt


def _levels(min_: int | None, max_: int | None) -> str:
    return f"{min_}-{max_}" if min_ is not None and max_ is not None else ""


def _pdf_excerpt(cp: CodexProduct, product: Product) -> Excerpt | None:
    path = product.extracted_text_path
    if not path or not Path(path).exists():
        return None
    with open(path, encoding="utf-8") as f:
        text_json = json.load(f)
    publisher, folder = product_folder(product.file_path) or ("", "")
    header = {
        "filename": product.file_name,
        "publisher_folder": publisher,
        "product_folder": folder,
        "page_count": "" if product.page_count is None else str(product.page_count),
        "codex_title": cp.title,
        "grimoire_type": product.product_type or "",
        "grimoire_levels": _levels(product.level_range_min, product.level_range_max),
    }
    return build_excerpt(text_json, header)


async def build_items(db: AsyncSession, *, pilot: bool = False, all_: bool = False,
                      slugs: list[str] | None = None) -> list[RunItem]:
    query = select(CodexProduct).order_by(CodexProduct.slug)
    if pilot:
        query = query.where(CodexProduct.in_pilot.is_(True))
    elif slugs is not None:
        query = query.where(CodexProduct.slug.in_(slugs))
    elif not all_:
        raise ValueError("choose pilot, all_, or slugs")

    items = []
    for cp in (await db.execute(query)).scalars():
        product = await db.get(Product, cp.grimoire_product_id) if cp.grimoire_product_id else None
        excerpt = _pdf_excerpt(cp, product) if product else None
        if excerpt is None:
            # No Grimoire file, or a matched file with no extracted text: read the
            # Codex blurb, but keep the product so apply can still write to it.
            excerpt = build_description_excerpt(cp)
        items.append(RunItem(cp.id, product.id if product else None, excerpt.source, excerpt))
    return items


async def _old_values(db: AsyncSession, item: RunItem) -> tuple:
    if item.product_id is not None:
        p = await db.get(Product, item.product_id)
        return p.product_type, p.level_range_min, p.level_range_max
    cp = await db.get(CodexProduct, item.codex_product_id)
    return cp.product_type, cp.level_range_min, cp.level_range_max


async def submit_run(db: AsyncSession, client, name: str, model: str, effort: str,
                     items: list[RunItem]) -> ClassificationRun:
    if (await db.execute(select(ClassificationRun).where(ClassificationRun.name == name))).scalar():
        raise ValueError(f"run {name!r} already exists")
    run = ClassificationRun(name=name, model=model, effort=effort, request_count=len(items))
    db.add(run)
    await db.flush()

    for item in items:
        type_old, min_old, max_old = await _old_values(db, item)
        db.add(ClassificationResult(
            run_id=run.id, product_id=item.product_id, codex_product_id=item.codex_product_id,
            source=item.source, product_type_old=type_old,
            level_min_old=min_old, level_max_old=max_old,
        ))

    batch_ids = []
    for start in range(0, len(items), MAX_BATCH_REQUESTS):
        chunk = items[start:start + MAX_BATCH_REQUESTS]
        requests = [build_request(i.codex_product_id, i.excerpt.text, model, effort) for i in chunk]
        batch_ids.append(client.messages.batches.create(requests=requests).id)

    run.batch_id = ",".join(batch_ids)
    run.status = "submitted"
    run.submitted_at = _now()
    await db.flush()
    return run


def _error_text(result) -> str:
    detail = getattr(getattr(result, "error", None), "error", None)
    if detail is not None:
        return f"{result.type}: {detail.type}: {detail.message}"
    return result.type


def _store(row: ClassificationResult, result) -> tuple[bool, int, int]:
    """Fill one row from one batch result. Returns (stored, input, output tokens)."""
    if result.type != "succeeded":
        row.error = _error_text(result)
        return False, 0, 0

    message = result.message
    u = message.usage
    tokens_in = (u.input_tokens + (u.cache_creation_input_tokens or 0)
                 + (u.cache_read_input_tokens or 0))
    tokens_out = u.output_tokens
    text = next((b.text for b in message.content if b.type == "text"), "")
    row.raw_response = text
    if message.stop_reason in ("max_tokens", "refusal"):
        row.error = f"stop_reason: {message.stop_reason}"
        return False, tokens_in, tokens_out
    try:
        out = parse_output(text)
    except ValueError as exc:
        row.error = str(exc)
        return False, tokens_in, tokens_out

    row.error = None
    # The schema still allows magazine; every periodical is stored as zine.
    row.product_type_new = normalize_free_text(out.product_type)
    row.level_min_new = out.level_range_min
    row.level_max_new = out.level_range_max
    row.confidence = out.confidence
    row.type_evidence = out.type_evidence
    row.level_evidence = out.level_evidence
    row.notes = out.notes
    return True, tokens_in, tokens_out


async def collect_run(db: AsyncSession, client, name: str, wait: bool = False,
                      poll_seconds: int = 60) -> dict[str, int]:
    run = (await db.execute(select(ClassificationRun).where(ClassificationRun.name == name))).scalar_one()
    batch_ids = [b for b in (run.batch_id or "").split(",") if b]

    while True:
        statuses = [client.messages.batches.retrieve(b) for b in batch_ids]
        pending = sum(s.request_counts.processing for s in statuses if s.processing_status != "ended")
        if all(s.processing_status == "ended" for s in statuses):
            break
        if not wait:
            return {"pending": pending}
        await asyncio.sleep(poll_seconds)

    rows = {
        r.codex_product_id: r
        for r in (await db.execute(
            select(ClassificationResult).where(ClassificationResult.run_id == run.id)
        )).scalars()
    }
    counts = {"stored": 0, "error": 0}
    # Totals are recomputed from the full result set, so collecting twice is safe.
    run.input_tokens = run.output_tokens = 0
    returned: set[str] = set()
    for batch_id in batch_ids:
        for entry in client.messages.batches.results(batch_id):
            row = rows.get(entry.custom_id)
            if row is None:
                continue
            returned.add(entry.custom_id)
            stored, tokens_in, tokens_out = _store(row, entry.result)
            counts["stored" if stored else "error"] += 1
            run.input_tokens += tokens_in
            run.output_tokens += tokens_out
    # Every batch has ended, so a row with no result never gets one. Left
    # without an error, apply would read its null type as the decision.
    for custom_id, row in rows.items():
        if custom_id not in returned:
            row.error = "no result returned"
            counts["error"] += 1

    run.cost_usd = cost_usd(run.model, run.input_tokens, run.output_tokens)
    run.status = "collected"
    run.completed_at = _now()
    await db.flush()
    return counts
