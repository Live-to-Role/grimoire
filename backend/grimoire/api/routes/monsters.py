"""Bestiary API - extracted monster entries, encounter rolls, metrics."""

import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from grimoire.api.deps import DbSession
from grimoire.models import BestiaryFavorite, MonsterEntry, ProcessingQueue, Product
from grimoire.processors.system_profiles import PROFILES
from grimoire.services.monster_metrics import compute_metrics
from grimoire.utils.dice import dice_average, parse_dice

router = APIRouter()

VALID_STATUSES = {"pending", "confirmed", "rejected"}


class ExtractRequest(BaseModel):
    system_profile: str
    provider: str | None = None
    model: str | None = None


class PatchEntryRequest(BaseModel):
    name: str | None = None
    page_number: int | None = None
    ac: int | None = None
    hd_dice: str | None = None
    attacks: list[dict] | None = None
    move: str | None = None
    special_abilities: list[str] | None = None
    environments: list[str] | None = None
    review_status: str | None = None


class RandomRequest(BaseModel):
    count: int = Field(3, ge=1, le=50)
    environment: str | None = None
    system_profile: str | None = None
    hd_min: float | None = None
    hd_max: float | None = None
    product_ids: list[int] | None = None


class BulkStatusRequest(BaseModel):
    ids: list[int]
    review_status: str


class FavoriteRequest(BaseModel):
    name: str | None = None
    config: dict | None = None


def _entry_to_dict(entry: MonsterEntry, product_title: str | None = None) -> dict:
    return {
        "id": entry.id,
        "product_id": entry.product_id,
        "product_title": product_title,
        "name": entry.name,
        "page_number": entry.page_number,
        "system_profile": entry.system_profile,
        "raw_text": entry.raw_text,
        "ac": entry.ac,
        "hd_dice": entry.hd_dice,
        "hd_value": entry.hd_value,
        "hp_avg": entry.hp_avg,
        "attacks": json.loads(entry.attacks) if entry.attacks else [],
        "move": entry.move,
        "special_abilities": json.loads(entry.special_abilities) if entry.special_abilities else [],
        "environments": json.loads(entry.environments) if entry.environments else [],
        "extraction_confidence": entry.extraction_confidence,
        "flags": json.loads(entry.flags) if entry.flags else [],
        "review_status": entry.review_status,
    }


def _base_conditions(
    environment: str | None = None,
    system_profile: str | None = None,
    product_ids: list[int] | None = None,
    review_status: str | None = "confirmed",
    hd_min: float | None = None,
    hd_max: float | None = None,
    q: str | None = None,
) -> list:
    conditions = []
    if review_status:
        conditions.append(MonsterEntry.review_status == review_status)
    if environment:
        conditions.append(MonsterEntry.environments.like(f'%"{environment}"%'))
    if system_profile:
        conditions.append(MonsterEntry.system_profile == system_profile)
    if product_ids:
        conditions.append(MonsterEntry.product_id.in_(product_ids))
    if hd_min is not None:
        conditions.append(MonsterEntry.hd_value >= hd_min)
    if hd_max is not None:
        conditions.append(MonsterEntry.hd_value <= hd_max)
    if q:
        conditions.append(MonsterEntry.name.ilike(f"%{q}%"))
    return conditions


def _profile_candidate_counts(pages: list[dict]) -> dict[str, int]:
    """Candidate count per registered profile. Pure regex, no LLM - free to run."""
    from grimoire.processors.monster_segmenter import segment_pages

    return {pid: len(segment_pages(pages, profile)) for pid, profile in PROFILES.items()}


@router.post("/extract/{product_id}")
async def enqueue_extract(db: DbSession, product_id: int, request: ExtractRequest) -> dict:
    """Queue monster extraction, refusing profiles that cannot possibly work.

    Keys off content, not game_system metadata: metadata is unreliable (one
    known product is labelled Old-School Essentials while being byte-identical
    to a DCC book). Metadata only phrases the error message.
    """
    from grimoire.services import processor as _processor

    if request.system_profile not in PROFILES:
        raise HTTPException(status_code=400, detail=f"Unknown system profile: {request.system_profile}")

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not product.text_extracted:
        raise HTTPException(status_code=400, detail="Product has no extracted text")

    pages = _processor.get_extracted_pages(product)
    if not pages:
        raise HTTPException(
            status_code=400,
            detail="Product has no page-anchored text. Re-run text extraction first.",
        )

    counts = _profile_candidate_counts(pages)
    chosen = counts.get(request.system_profile, 0)
    if chosen == 0:
        supported = ", ".join(p.label for p in PROFILES.values())
        detail = (
            f"No stat blocks found in '{product.title or product.file_name}' using the "
            f"{PROFILES[request.system_profile].label} profile. Supported systems: {supported}."
        )
        if product.game_system:
            detail += f" This book is labelled '{product.game_system}'."
        raise HTTPException(status_code=400, detail=detail)

    existing = await db.execute(select(ProcessingQueue).where(
        ProcessingQueue.product_id == product_id,
        ProcessingQueue.task_type == "monster_extract",
        ProcessingQueue.status.in_(["pending", "processing"]),
    ))
    if existing.scalars().first():
        return {"queued": False, "message": "Extraction already queued for this product", "counts": counts}

    config = {"system_profile": request.system_profile}
    if request.provider:
        config["provider"] = request.provider
    if request.model:
        config["model"] = request.model
    db.add(ProcessingQueue(
        product_id=product_id,
        task_type="monster_extract",
        # Interactive, one-off, owner-triggered action — preempt bulk work
        # (text re-extraction etc. queues at priority=5) rather than sorting
        # to the back of that band behind thousands of backlog items.
        priority=9,
        status="pending",
        config=json.dumps(config),
    ))
    await db.commit()

    response = {
        "queued": True,
        "message": f"Monster extraction queued ({request.system_profile})",
        "counts": counts,
    }

    # Loose on purpose: the OSR anchor also matches DCC stat lines, so those
    # two counts do not separate cleanly. This catches DCC-vs-5e-scale
    # mistakes, and only ever warns.
    best_profile = max(counts, key=lambda k: counts[k])
    best = counts[best_profile]
    if best >= 20 and chosen * 2 < best:
        response["warning"] = (
            f"Queued with the {PROFILES[request.system_profile].label} profile "
            f"({chosen} stat blocks), but {PROFILES[best_profile].label} found {best}. "
            "Wrong profile?"
        )
    return response


@router.get("")
async def list_monsters(
    db: DbSession,
    environment: str | None = None,
    system_profile: str | None = None,
    # Annotated form, not `= Query(None)`: the latter makes the Python default a
    # Query object, which breaks calling this function directly (as the tests do).
    product_ids: Annotated[list[int] | None, Query()] = None,
    review_status: str = "confirmed",
    q: str | None = None,
    hd_min: float | None = None,
    hd_max: float | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """List monster entries with filters. Defaults to confirmed entries only."""
    per_page = max(1, min(per_page, 200))
    page = max(1, page)
    conditions = _base_conditions(environment, system_profile, product_ids, review_status, hd_min, hd_max, q)

    count_query = select(func.count(MonsterEntry.id)).where(*conditions)
    total = (await db.execute(count_query)).scalar() or 0

    query = (
        select(MonsterEntry, Product.title)
        .join(Product, Product.id == MonsterEntry.product_id)
        .where(*conditions)
        .order_by(MonsterEntry.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = (await db.execute(query)).all()
    return {"items": [_entry_to_dict(e, title) for e, title in rows], "total": total}


@router.get("/environments")
async def list_environments(db: DbSession) -> dict:
    """Distinct environment tags across confirmed entries."""
    result = await db.execute(
        select(MonsterEntry.environments).where(MonsterEntry.review_status == "confirmed")
    )
    tags: set[str] = set()
    for (raw,) in result:
        if raw:
            tags.update(json.loads(raw))
    return {"environments": sorted(tags)}


@router.get("/books")
async def list_books(db: DbSession, review_status: str = "confirmed") -> dict:
    """Books that have entries at the given review status, for the book filter.

    Takes review_status because a freshly extracted book has only pending
    entries: a confirmed-only listing would offer no books to filter by at
    exactly the moment you are reviewing that book.
    """
    query = (
        select(MonsterEntry.product_id, Product.title, func.count(MonsterEntry.id))
        .join(Product, Product.id == MonsterEntry.product_id)
        .where(MonsterEntry.review_status == review_status)
        .group_by(MonsterEntry.product_id, Product.title)
        .order_by(Product.title)
    )
    rows = (await db.execute(query)).all()
    return {
        "books": [
            {"product_id": product_id, "title": title, "count": count}
            for product_id, title, count in rows
        ]
    }


def _favorite_to_dict(favorite: BestiaryFavorite) -> dict:
    return {
        "id": favorite.id,
        "name": favorite.name,
        "config": json.loads(favorite.config) if favorite.config else {},
    }


@router.get("/favorites")
async def list_favorites(db: DbSession) -> dict:
    """Saved bestiary queries, newest first."""
    result = await db.execute(
        select(BestiaryFavorite).order_by(BestiaryFavorite.created_at.desc(), BestiaryFavorite.id.desc())
    )
    return {"favorites": [_favorite_to_dict(f) for f in result.scalars().all()]}


@router.post("/favorites")
async def create_favorite(db: DbSession, request: FavoriteRequest) -> dict:
    """Save the current query under a name."""
    if not request.name or not request.name.strip():
        raise HTTPException(status_code=422, detail="name is required")

    favorite = BestiaryFavorite(
        name=request.name.strip(),
        config=json.dumps(request.config or {}),
    )
    db.add(favorite)
    await db.commit()
    await db.refresh(favorite)
    return _favorite_to_dict(favorite)


@router.patch("/favorites/{favorite_id}")
async def update_favorite(db: DbSession, favorite_id: int, request: FavoriteRequest) -> dict:
    """Rename a favorite, overwrite its query, or both."""
    result = await db.execute(select(BestiaryFavorite).where(BestiaryFavorite.id == favorite_id))
    favorite = result.scalar_one_or_none()
    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite not found")

    if request.name is not None:
        if not request.name.strip():
            raise HTTPException(status_code=422, detail="name cannot be blank")
        favorite.name = request.name.strip()
    if request.config is not None:
        favorite.config = json.dumps(request.config)

    await db.commit()
    await db.refresh(favorite)
    return _favorite_to_dict(favorite)


@router.delete("/favorites/{favorite_id}")
async def delete_favorite(db: DbSession, favorite_id: int) -> dict:
    """Remove a saved query."""
    result = await db.execute(select(BestiaryFavorite).where(BestiaryFavorite.id == favorite_id))
    favorite = result.scalar_one_or_none()
    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite not found")

    await db.delete(favorite)
    await db.commit()
    return {"deleted": True}


@router.post("/bulk-status")
async def bulk_status(db: DbSession, request: BulkStatusRequest) -> dict:
    """Set review_status on many entries in one transaction.

    One UPDATE and one commit, rather than one request per entry: confirming
    175 entries via PATCH took over five minutes because each request forced
    its own fsync against a large database.
    """
    if request.review_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"review_status must be one of {sorted(VALID_STATUSES)}"
        )
    if not request.ids:
        return {"updated": 0}

    result = await db.execute(
        update(MonsterEntry)
        .where(MonsterEntry.id.in_(request.ids))
        .values(review_status=request.review_status)
    )
    await db.commit()
    # rowcount reflects rows that actually existed, so unknown ids are skipped
    # silently but visibly — the caller can compare against len(ids).
    return {"updated": result.rowcount or 0}


@router.patch("/{entry_id}")
async def patch_entry(db: DbSession, entry_id: int, request: PatchEntryRequest) -> dict:
    """Edit an entry; recompute derived fields when dice change."""
    result = await db.execute(select(MonsterEntry).where(MonsterEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    if request.review_status is not None:
        if request.review_status not in VALID_STATUSES:
            raise HTTPException(status_code=422, detail=f"review_status must be one of {sorted(VALID_STATUSES)}")
        entry.review_status = request.review_status

    for field in ("name", "page_number", "ac", "move"):
        value = getattr(request, field)
        if value is not None:
            setattr(entry, field, value)

    if request.hd_dice is not None:
        entry.hd_dice = request.hd_dice
        entry.hp_avg = dice_average(request.hd_dice)
        parsed = parse_dice(request.hd_dice)
        entry.hd_value = float(parsed[0]) if parsed else None

    if request.attacks is not None:
        attacks = []
        for atk in request.attacks:
            atk = dict(atk)
            atk["damage_avg"] = dice_average(atk.get("damage_dice"))
            attacks.append(atk)
        entry.attacks = json.dumps(attacks)

    if request.special_abilities is not None:
        entry.special_abilities = json.dumps(request.special_abilities)
    if request.environments is not None:
        entry.environments = json.dumps(request.environments)

    await db.commit()
    await db.refresh(entry)
    return _entry_to_dict(entry)


@router.get("/{entry_id}/metrics")
async def get_entry_metrics(db: DbSession, entry_id: int) -> dict:
    """Closed-form combat metrics for one entry."""
    result = await db.execute(select(MonsterEntry).where(MonsterEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return compute_metrics(entry)


@router.post("/random")
async def random_monsters(db: DbSession, request: RandomRequest) -> dict:
    """Random confirmed monsters matching filters (encounter roll / table rows)."""
    conditions = _base_conditions(
        environment=request.environment,
        system_profile=request.system_profile,
        product_ids=request.product_ids,
        review_status="confirmed",
        hd_min=request.hd_min,
        hd_max=request.hd_max,
    )
    query = (
        select(MonsterEntry, Product.title)
        .join(Product, Product.id == MonsterEntry.product_id)
        .where(*conditions)
        .order_by(func.random())
        .limit(request.count)
    )
    rows = (await db.execute(query)).all()
    return {"items": [_entry_to_dict(e, title) for e, title in rows]}
