"""Send a run's decisions to Codex's classification override endpoint.

A dry run (Codex's default) reports what each item would do; the report CSV
it produces is what Michael reviews, and only its `send = yes` rows go live.
Only fields that differ from Codex travel, null never travels, and `other`
never replaces a specific Codex type (spec §8).
"""

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.config import settings
from grimoire.models import Setting
from grimoire.models.classification import ClassificationResult, ClassificationRun, CodexProduct
from grimoire.services.classification.apply import effective_levels
from grimoire.services.classification.enum import CODEX_PRODUCT_TYPES
from grimoire.services.classification.pilot import _text_cell

CHUNK = 100  # Codex's per-request limit
LOW_CONFIDENCE = 0.6
LEVEL_FIELDS = ("level_range_min", "level_range_max")
_EMPTY = (None, "", "other")


@dataclass
class ExportItem:
    codex_id: str
    slug: str
    title: str
    fields: dict[str, int | str]
    kinds: dict[str, str]
    confidence: float | None
    type_evidence: str | None
    level_evidence: str | None
    old: dict[str, int | str | None] = field(default_factory=dict)
    # Other Codex products classified from the same Grimoire file, e.g. a
    # promo insert that is the only PDF in several map packs' folders.
    shared_with: int = 0


def _kind(codex_value) -> str:
    return "fill" if codex_value in _EMPTY else "correction"


async def _collected_run(db: AsyncSession, run_name: str) -> ClassificationRun:
    run = (await db.execute(
        select(ClassificationRun).where(ClassificationRun.name == run_name)
    )).scalar()
    if run is None:
        raise ValueError(f"no run named {run_name!r}")
    if run.status != "collected":
        raise ValueError(f"run {run_name!r} is {run.status}, not collected")
    return run


async def build_items(db: AsyncSession, run_name: str,
                      min_confidence: float = 0.0) -> list[ExportItem]:
    run = await _collected_run(db, run_name)
    rows = (await db.execute(
        select(ClassificationResult, CodexProduct)
        .join(CodexProduct, CodexProduct.id == ClassificationResult.codex_product_id)
        .where(ClassificationResult.run_id == run.id, ClassificationResult.error.is_(None))
        .order_by(CodexProduct.slug)
    )).all()
    per_file = Counter(r.product_id for r, _ in rows if r.product_id is not None)

    items = []
    for r, cx in rows:
        if (r.confidence or 0.0) < min_confidence:
            continue
        fields: dict[str, int | str] = {}
        kinds: dict[str, str] = {}
        new_type = r.product_type_new
        if (new_type in CODEX_PRODUCT_TYPES and new_type != cx.product_type
                and not (new_type == "other" and cx.product_type not in _EMPTY)):
            fields["product_type"] = new_type
            kinds["product_type"] = _kind(cx.product_type)
        lo, hi = effective_levels(r.level_min_new, r.level_max_new)
        if lo is not None:
            for name, new, old in ((LEVEL_FIELDS[0], lo, cx.level_range_min),
                                   (LEVEL_FIELDS[1], hi, cx.level_range_max)):
                if new != old:
                    fields[name] = new
                    kinds[name] = _kind(old)
        if not fields:
            continue
        items.append(ExportItem(
            codex_id=cx.id, slug=cx.slug, title=cx.title, fields=fields, kinds=kinds,
            confidence=r.confidence, type_evidence=r.type_evidence,
            level_evidence=r.level_evidence,
            old={"product_type": cx.product_type, LEVEL_FIELDS[0]: cx.level_range_min,
                 LEVEL_FIELDS[1]: cx.level_range_max},
            shared_with=per_file[r.product_id] - 1 if r.product_id is not None else 0,
        ))
    return items


async def codex_token(db: AsyncSession) -> str:
    row = await db.get(Setting, "codex_api_key")
    token = json.loads(row.value) if row is not None else ""
    token = token or settings.codex_api_key
    if not token:
        raise RuntimeError("No Codex API token in settings or CODEX_API_KEY")
    return token


def send_items(items: list[ExportItem], token: str, dry_run: bool,
               client: httpx.Client | None = None) -> dict[str, dict]:
    """POST in chunks; returns each item's result object keyed by Codex id."""
    own = client is None
    client = client or httpx.Client(base_url=settings.codex_api_url, timeout=120)
    headers = {
        "Authorization": f"Token {token}",
        # Cloudflare answers 403 (error 1010) to python-httpx's default agent.
        "User-Agent": "Grimoire/classification",
    }
    outcomes: dict[str, dict] = {}
    try:
        for start in range(0, len(items), CHUNK):
            chunk = items[start:start + CHUNK]
            body = {"dry_run": dry_run,
                    "items": [{"id": i.codex_id, **i.fields} for i in chunk]}
            response = client.post("/classification/", json=body, headers=headers)
            response.raise_for_status()
            for result in response.json()["results"]:
                outcomes[result["key"]] = result
    finally:
        if own:
            client.close()
    return outcomes


REPORT_COLUMNS = [
    "send", "codex_id", "slug", "title", "type_old", "type_new", "type_kind",
    "min_old", "min_new", "max_old", "max_new", "level_kind", "confidence",
    "type_evidence", "level_evidence", "codex_status", "protected", "errors", "shared_file",
]


def _cell(value) -> str:
    return "" if value is None else str(value)


def _level_kind(item: ExportItem) -> str:
    kinds = [item.kinds[f] for f in LEVEL_FIELDS if f in item.kinds]
    if not kinds:
        return ""
    return "correction" if "correction" in kinds else "fill"


def write_report(items: list[ExportItem], outcomes: dict[str, dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel, where the review happens, reads the encoding right.
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(REPORT_COLUMNS)
        for i in items:
            o = outcomes.get(i.codex_id, {})
            writer.writerow([
                "yes", i.codex_id, i.slug, _text_cell(i.title),
                _cell(i.old.get("product_type")), _cell(i.fields.get("product_type")),
                i.kinds.get("product_type", ""),
                _cell(i.old.get(LEVEL_FIELDS[0])), _cell(i.fields.get(LEVEL_FIELDS[0])),
                _cell(i.old.get(LEVEL_FIELDS[1])), _cell(i.fields.get(LEVEL_FIELDS[1])),
                _level_kind(i), _cell(i.confidence),
                _text_cell(i.type_evidence), _text_cell(i.level_evidence),
                o.get("status", ""), ";".join(o.get("protected") or []),
                _text_cell("; ".join(o.get("errors") or [])),
                i.shared_with or "",
            ])
    print(summarize(items, outcomes))


def summarize(items: list[ExportItem], outcomes: dict[str, dict]) -> str:
    kinds = Counter(f"{name.replace('level_range_', '')} {kind}"
                    for i in items for name, kind in i.kinds.items())
    statuses = Counter(outcomes.get(i.codex_id, {}).get("status", "not sent") for i in items)
    moves = Counter((i.old.get("product_type"), i.fields["product_type"])
                    for i in items if "product_type" in i.fields)
    low = sum((i.confidence or 0.0) < LOW_CONFIDENCE for i in items)
    shared = sum(i.shared_with > 0 for i in items)
    lines = [f"{len(items)} items"]
    lines.append("by kind: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
    lines.append("by status: " + ", ".join(f"{k} {n}" for k, n in statuses.most_common()))
    lines.append("top type transitions:")
    lines += [f"  {a} -> {b}: {n}" for (a, b), n in moves.most_common(10)]
    lines.append(f"confidence < {LOW_CONFIDENCE}: {low}")
    lines.append(f"classified from a file shared with another Codex product: {shared}")
    return "\n".join(lines)


def _int(cell: str) -> int | None:
    cell = (cell or "").strip()
    return int(cell) if cell else None


def read_reviewed(path: Path) -> list[ExportItem]:
    items = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("send") or "").strip().lower() != "yes":
                continue
            fields: dict[str, int | str] = {}
            if (row.get("type_new") or "").strip():
                fields["product_type"] = row["type_new"].strip()
            for name, column in ((LEVEL_FIELDS[0], "min_new"), (LEVEL_FIELDS[1], "max_new")):
                value = _int(row.get(column, ""))
                if value is not None:
                    fields[name] = value
            if not fields:
                continue
            kinds = {}
            if "product_type" in fields:
                kinds["product_type"] = row.get("type_kind", "")
            for name in LEVEL_FIELDS:
                if name in fields:
                    kinds[name] = row.get("level_kind", "")
            confidence = (row.get("confidence") or "").strip()
            items.append(ExportItem(
                codex_id=row["codex_id"], slug=row["slug"], title=row["title"],
                fields=fields, kinds=kinds,
                confidence=float(confidence) if confidence else None,
                type_evidence=row.get("type_evidence") or None,
                level_evidence=row.get("level_evidence") or None,
            ))
    return items


async def stamp_exported(db: AsyncSession, run_name: str, outcomes: dict[str, dict]) -> int:
    """Record each live item's Codex status on the run's result rows."""
    run = await _collected_run(db, run_name)
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = (await db.execute(
        select(ClassificationResult).where(
            ClassificationResult.run_id == run.id,
            ClassificationResult.codex_product_id.in_(list(outcomes)),
        )
    )).scalars()
    count = 0
    for r in rows:
        r.exported_status = outcomes[r.codex_product_id]["status"]
        r.exported_at = now
        count += 1
    await db.commit()
    return count
