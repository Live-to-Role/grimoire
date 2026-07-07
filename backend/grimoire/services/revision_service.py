"""Revision detection service — identifies products that are revisions of each other."""

import re
from datetime import datetime
from itertools import groupby
from pathlib import Path

from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models.product import Product

# Trailing format tags to strip (case-insensitive)
FORMAT_TAGS = [
    r"[-_]PDF",
]

# Trailing revision patterns to strip (case-insensitive)
# Order matters: longer/more specific patterns first
REVISION_PATTERNS = [
    r"\(Print[_ ]Friendly\)",
    r"[-_]2nd[_ ]Edition",
    r"[-_]3rd[_ ]Edition",
    r"[-_]Revised",
    r"\(Revised\)",
    r"[-_]Updated",
    r"\(Updated\)",
    r"[-_]Errata",
    r"\(Errata\)",
    r"[-_]Final",
    r"\(Final\)",
    r"[-_]v\d+(?:\.\d+)?",  # _v2, _v1.2
]

# Combined pattern for detecting if a filename has any revision indicator (trailing only)
_REVISION_DETECT_RE = re.compile(
    r"(?:" + "|".join(REVISION_PATTERNS) + r")\s*$",
    re.IGNORECASE,
)

# Build a single regex that strips trailing format tags and revision patterns
# Apply iteratively since a filename may have both (e.g., "Adventure-PDF_(Revised)")
_FORMAT_TAG_RE = re.compile(
    r"(?:" + "|".join(FORMAT_TAGS) + r")\s*$",
    re.IGNORECASE,
)
_REVISION_PATTERN_RE = re.compile(
    r"(?:" + "|".join(REVISION_PATTERNS) + r")\s*$",
    re.IGNORECASE,
)
_TRAILING_SEP_RE = re.compile(r"[-_ ]+$")
_SEPARATOR_RE = re.compile(r"[-_ ]+")


def normalize_stem(filename: str) -> str:
    """Normalize a filename to a canonical stem for revision matching.

    Steps:
    1. Remove file extension
    2. Strip trailing format tags (-PDF, _PDF)
    3. Strip trailing revision patterns (_Revised, _v2, etc.)
    4. Lowercase, collapse separators, strip trailing separators
    """
    stem = Path(filename).stem

    # Iteratively strip format tags and revision patterns from the end
    # Loop because stripping one may reveal another (e.g., "Foo-PDF_(Revised)")
    changed = True
    while changed:
        changed = False
        new_stem = _FORMAT_TAG_RE.sub("", stem)
        if new_stem != stem:
            stem = _TRAILING_SEP_RE.sub("", new_stem)
            changed = True
        new_stem = _REVISION_PATTERN_RE.sub("", stem)
        if new_stem != stem:
            stem = _TRAILING_SEP_RE.sub("", new_stem)
            changed = True

    # Lowercase, collapse separators
    stem = stem.lower()
    stem = _SEPARATOR_RE.sub("_", stem)
    stem = stem.strip("_")

    return stem


def has_revision_indicator(filename: str) -> bool:
    """Check if a filename contains a trailing revision indicator."""
    stem = Path(filename).stem
    # Strip format tags first so "Foo-PDF_(Revised)" works
    stem = _FORMAT_TAG_RE.sub("", stem)
    return bool(_REVISION_DETECT_RE.search(stem))


# --- Database-level functions ---

async def find_revision_candidates(db: AsyncSession) -> list[dict]:
    """Find groups of products that share a normalized_stem but have different hashes.

    Returns list of groups: [{"normalized_stem": str, "products": [Product, ...]}]
    Excludes products already marked as duplicates, superseded, or missing.
    """
    # Find stems with >1 non-excluded product
    stem_counts = (
        select(Product.normalized_stem, func.count(Product.id).label("cnt"))
        .where(
            Product.normalized_stem.isnot(None),
            Product.is_duplicate == False,
            Product.is_superseded == False,
            Product.is_missing == False,
        )
        .group_by(Product.normalized_stem)
        .having(func.count(Product.id) > 1)
    )
    result = await db.execute(stem_counts)
    stems = [row.normalized_stem for row in result.all()]

    if not stems:
        return []

    # Fetch products for those stems
    query = (
        select(Product)
        .where(
            Product.normalized_stem.in_(stems),
            Product.is_duplicate == False,
            Product.is_superseded == False,
            Product.is_missing == False,
        )
        .order_by(Product.normalized_stem)
    )
    result = await db.execute(query)
    products = result.scalars().all()

    # Group by stem, only keep groups with >1 distinct hash
    groups = []
    for stem, group_iter in groupby(products, key=lambda p: p.normalized_stem):
        group_products = list(group_iter)
        hashes = {p.file_hash for p in group_products}
        if len(hashes) > 1:
            groups.append({
                "normalized_stem": stem,
                "products": group_products,
            })

    return groups


def determine_newer_product(products: list[Product]) -> Product:
    """Determine which product in a group is the newest (canonical revision).

    Priority:
    1. Has a revision indicator in filename
    2. Most recent file_modified_at
    3. Most recent created_at
    """
    def sort_key(p: Product) -> tuple:
        has_indicator = has_revision_indicator(p.file_name) if p.file_name else False
        mtime = p.file_modified_at or datetime.min
        ctime = p.created_at or datetime.min
        return (has_indicator, mtime, ctime)

    return max(products, key=sort_key)


async def mark_revision_candidates(db: AsyncSession) -> int:
    """Find revision candidate groups and mark older products as revision duplicates.

    Returns count of newly marked candidates.
    """
    groups = await find_revision_candidates(db)
    marked = 0

    for group in groups:
        newer = determine_newer_product(group["products"])
        for product in group["products"]:
            if product.id != newer.id:
                product.is_duplicate = True
                product.duplicate_of_id = newer.id
                product.duplicate_reason = "revision"
                marked += 1

    if marked:
        await db.commit()

    return marked


# Fields to transfer during revision confirmation
TRANSFERABLE_FIELDS = [
    "title", "author", "publisher", "publication_year", "description",
    "game_system", "genre", "product_type", "setting",
    "series", "series_order",
    "level_range_min", "level_range_max",
    "party_size_min", "party_size_max",
    "estimated_runtime", "format", "isbn", "msrp",
    "dtrpg_url", "itch_url", "themes", "content_warnings",
]

RUN_FIELDS = ["run_status", "run_rating", "run_difficulty", "run_completed_at"]


async def confirm_revision(db: AsyncSession, old_product_id: int) -> dict:
    """Confirm a revision candidate: transfer metadata, supersede the old product.

    Returns dict with transfer summary.
    """
    result = await db.execute(select(Product).where(Product.id == old_product_id))
    old = result.scalar_one_or_none()
    if not old or old.duplicate_reason != "revision" or not old.duplicate_of_id:
        raise ValueError(f"Product {old_product_id} is not a revision candidate")

    result = await db.execute(select(Product).where(Product.id == old.duplicate_of_id))
    new = result.scalar_one_or_none()
    if not new:
        raise ValueError(f"Newer product {old.duplicate_of_id} not found")

    # 1. Selective metadata transfer
    transferred = []
    for field in TRANSFERABLE_FIELDS:
        old_val = getattr(old, field)
        new_val = getattr(new, field)
        if old_val is not None and (new_val is None or new_val == "" or new_val == []):
            setattr(new, field, old_val)
            transferred.append(field)

    # 2. Relationship transfer (tags, collections)
    from grimoire.models.tag import ProductTag
    try:
        from grimoire.models.collection import CollectionProduct
        has_collections = True
    except ImportError:
        has_collections = False

    # Transfer tags
    old_tags_result = await db.execute(
        select(ProductTag).where(ProductTag.product_id == old.id)
    )
    for tag_assoc in old_tags_result.scalars().all():
        existing = await db.execute(
            select(ProductTag).where(
                ProductTag.product_id == new.id,
                ProductTag.tag_id == tag_assoc.tag_id,
            )
        )
        if not existing.scalar_one_or_none():
            db.add(ProductTag(product_id=new.id, tag_id=tag_assoc.tag_id))

    # Transfer collections if model exists
    if has_collections:
        old_colls_result = await db.execute(
            select(CollectionProduct).where(CollectionProduct.product_id == old.id)
        )
        for coll_assoc in old_colls_result.scalars().all():
            existing = await db.execute(
                select(CollectionProduct).where(
                    CollectionProduct.product_id == new.id,
                    CollectionProduct.collection_id == coll_assoc.collection_id,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(CollectionProduct(product_id=new.id, collection_id=coll_assoc.collection_id))

    # 3. Run tracking transfer (scalar fields + RunNote FK reassignment via bulk UPDATE)
    has_run_data = any(getattr(new, f) is not None for f in RUN_FIELDS)
    if not has_run_data:
        for field in RUN_FIELDS:
            old_val = getattr(old, field)
            if old_val is not None:
                setattr(new, field, old_val)

        # Reassign RunNote records via bulk UPDATE to avoid cascade delete-orphan
        from grimoire.models.run_note import RunNote
        await db.execute(
            sa_update(RunNote)
            .where(RunNote.product_id == old.id)
            .values(product_id=new.id)
        )

    # 4. Supersede the old product
    old.is_superseded = True
    old.superseded_by_id = new.id
    old.is_duplicate = False
    old.duplicate_of_id = None
    old.duplicate_reason = None

    await db.commit()

    return {"transferred_fields": transferred, "old_id": old.id, "new_id": new.id}


async def dismiss_revision(db: AsyncSession, old_product_id: int) -> None:
    """Dismiss a revision candidate: clear all duplicate/revision markers."""
    result = await db.execute(select(Product).where(Product.id == old_product_id))
    old = result.scalar_one_or_none()
    if not old:
        raise ValueError(f"Product {old_product_id} not found")

    old.is_duplicate = False
    old.duplicate_of_id = None
    old.duplicate_reason = None

    await db.commit()


async def cleanup_orphaned_superseded(db: AsyncSession) -> dict:
    """Clear is_superseded on products whose superseded_by target no longer exists."""
    subq = select(Product.id)
    result = await db.execute(
        select(Product).where(
            Product.is_superseded == True,
            Product.superseded_by_id.isnot(None),
            ~Product.superseded_by_id.in_(subq),
        )
    )
    orphans = result.scalars().all()

    for product in orphans:
        product.is_superseded = False
        product.superseded_by_id = None

    if orphans:
        await db.commit()

    return {"cleaned": len(orphans)}


async def get_revision_groups(db: AsyncSession) -> list[dict]:
    """Get revision candidate groups for the API (already-marked candidates)."""
    result = await db.execute(
        select(Product).where(Product.duplicate_reason == "revision")
    )
    candidates = result.scalars().all()

    # Group by normalized_stem
    groups_by_stem: dict[str, list] = {}
    newer_ids = set()
    for c in candidates:
        stem = c.normalized_stem
        if stem not in groups_by_stem:
            groups_by_stem[stem] = []
        groups_by_stem[stem].append(c)
        if c.duplicate_of_id:
            newer_ids.add(c.duplicate_of_id)

    # Fetch the newer products
    if newer_ids:
        result = await db.execute(select(Product).where(Product.id.in_(newer_ids)))
        newer_products = {p.id: p for p in result.scalars().all()}
    else:
        newer_products = {}

    groups = []
    for stem, old_products in groups_by_stem.items():
        newer_id = old_products[0].duplicate_of_id
        newer = newer_products.get(newer_id)
        groups.append({
            "normalized_stem": stem,
            "newer": {
                "id": newer.id, "title": newer.title,
                "file_name": newer.file_name, "file_path": newer.file_path,
            } if newer else None,
            "older": [
                {
                    "id": p.id, "title": p.title,
                    "file_name": p.file_name, "file_path": p.file_path,
                }
                for p in old_products
            ],
        })

    return groups
