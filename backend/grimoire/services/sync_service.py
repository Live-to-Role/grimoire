"""Service for syncing metadata with Codex."""

import hashlib
import json
import logging
from datetime import datetime, UTC
from typing import Any

from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.config import settings
from grimoire.models import Product, ContributionQueue, ContributionStatus, Setting
from grimoire.services.codex import (
    CodexClient,
    CodexLookupError,
    CodexMatch,
    CodexProduct,
    get_codex_client,
    IdentificationSource,
    MatchType,
)
from grimoire.services.codex_eligibility import is_codex_eligible, may_share_cover
from grimoire.services.contribution_service import (
    CodexIneligibleError,
    queue_contribution,
    submit_all_pending,
)

logger = logging.getLogger(__name__)

# Fields that Codex tracks - used for no-change detection
CONTRIBUTION_FIELDS = [
    "title", "publisher", "author", "description", "game_system", "genre", 
    "product_type", "setting", "publication_year", "page_count", 
    "level_range_min", "level_range_max", "party_size_min", "party_size_max", 
    "estimated_runtime", "series", "series_order", "format", "isbn", "msrp",
    "dtrpg_url", "itch_url", "themes", "content_warnings",
]

# Valid Codex product types
CODEX_PRODUCT_TYPES = {
    "adventure", "sourcebook", "supplement", "bestiary",
    "tools", "magazine", "core_rules", "screen", "other",
}

# Mapping from Grimoire product types to Codex product types
PRODUCT_TYPE_MAPPING = {
    # Direct matches (case-insensitive)
    "adventure": "adventure",
    "sourcebook": "sourcebook",
    "supplement": "supplement",
    "bestiary": "bestiary",
    "screen": "screen",
    "other": "other",
    # Grimoire-specific mappings
    "core rulebook": "core_rules",
    "setting": "sourcebook",
    "character options": "supplement",
    "gm tools": "tools",
    "map": "other",
    "zine": "magazine",
    "magazine": "magazine",
    # Additional common variations
    "module": "adventure",
    "campaign": "adventure",
    "one-shot": "adventure",
    "art/maps": "other",
}


def _parse_json_array(value: str | None) -> list[str] | None:
    """
    Parse a JSON array string or comma-separated string into a list.
    
    Args:
        value: JSON array string like '["a", "b"]' or comma-separated like 'a, b'
        
    Returns:
        List of strings, or None if input is None/empty
    """
    if not value:
        return None
    
    value = value.strip()
    
    # Try JSON parse first
    if value.startswith('['):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if item]
        except json.JSONDecodeError:
            pass
    
    # Fall back to comma-separated
    items = [item.strip() for item in value.split(',') if item.strip()]
    return items if items else None


def normalize_product_type(product_type: str | None) -> str | None:
    """
    Normalize a Grimoire product type to a Codex-accepted value.
    
    Args:
        product_type: The product type from Grimoire
        
    Returns:
        Codex-compatible product type, or None if input is None
    """
    if not product_type:
        return None
    
    # Check direct match first (case-insensitive)
    normalized = product_type.lower().strip()
    
    # Check mapping
    if normalized in PRODUCT_TYPE_MAPPING:
        return PRODUCT_TYPE_MAPPING[normalized]
    
    # Check if already a valid Codex type
    if normalized in CODEX_PRODUCT_TYPES:
        return normalized
    
    # Default to "other" for unknown types
    logger.debug(f"Unknown product_type '{product_type}' mapped to 'other'")
    return "other"


async def resolve_include_cover(
    product: Product,
    client: CodexClient,
    match: "CodexMatch | None" = None,
    match_known: bool = False,
) -> bool:
    """Whether this contribution should carry a cover image.

    Two independent rules. `may_share_cover` keys on the product; the second
    keys on Codex already having one, which cannot help for a new_product —
    exactly where a scan's cover would be the first uploaded.

    Pass `match_known=True` with an already-fetched `match` to reuse a lookup
    the caller has made; otherwise this makes one. A scan short-circuits before
    any lookup at all, since no answer would change the result.
    """
    if not may_share_cover(product):
        return False

    if not match_known:
        try:
            match = await client.identify_by_hash(product.file_hash)
        except CodexLookupError:
            # Could not ask. Withhold rather than guess — a cover not sent
            # costs nothing, and one sent cannot be recalled.
            return False

    return not (match and match.product and match.product.cover_url)


async def should_contribute(
    product: Product,
    codex_client: CodexClient,
    on_match=None,
) -> tuple[bool, str]:
    """
    Check if this product's contribution would add value to Codex.
    
    Queries Codex for existing product data and compares with local data
    to determine if contribution adds new information.
    
    Args:
        product: Product to potentially contribute
        codex_client: CodexClient instance to query with
        
    Returns:
        Tuple of (should_contribute: bool, reason: str)
    """
    from grimoire.services.contribution_service import get_cover_image_base64

    # Checked before the lookup, so an ineligible product never costs a round
    # trip. This is the convenient place, not the safe one — see
    # queue_contribution for the guard that cannot be bypassed.
    eligible, reason = is_codex_eligible(product)
    if not eligible:
        return False, reason

    # Try to find existing product in Codex by hash
    try:
        match = await codex_client.identify_by_hash(product.file_hash)
    except CodexLookupError as e:
        # ⚠️ Never fall through to "new_product" here. A failed lookup is not
        # evidence that Codex lacks this product, and treating it as such turns
        # a throttle or a blip into a duplicate contribution for every
        # remaining product in the walk.
        logger.warning(f"Skipping {product.id}: could not ask Codex ({e})")
        return False, "lookup_failed"

    # Hand the lookup back so the caller need not repeat it. The cover rules
    # want the same match, and a second /identify per contribution is real
    # cost against an endpoint that throttles.
    if on_match is not None:
        on_match(match)

    if not match or not match.product:
        # New product - always contribute
        return True, "new_product"
    
    codex_product = match.product
    
    # Check if we have data Codex doesn't have
    for field in CONTRIBUTION_FIELDS:
        local_value = getattr(product, field, None)
        codex_value = getattr(codex_product, field, None)
        
        if local_value and not codex_value:
            return True, f"has_{field}"
    
    # Check cover image - if we have one and Codex doesn't
    if product.cover_extracted and product.cover_image_path:
        if not codex_product.cover_url:
            cover_b64 = get_cover_image_base64(product)
            if cover_b64:
                return True, "has_cover_image"
    
    # No new data to contribute
    return False, "no_new_data"


async def get_codex_settings_from_db(db: AsyncSession) -> tuple[bool, str | None]:
    """
    Get Codex settings from database (where frontend saves them).
    Falls back to env settings if not in database.
    
    Returns:
        Tuple of (contribute_enabled, api_key)
    """
    # Get API key from database
    query = select(Setting).where(Setting.key == "codex_api_key")
    result = await db.execute(query)
    setting = result.scalar_one_or_none()
    db_api_key = json.loads(setting.value) if setting else None
    
    # Get contribute_enabled from database
    query = select(Setting).where(Setting.key == "codex_contribute_enabled")
    result = await db.execute(query)
    setting = result.scalar_one_or_none()
    db_contribute_enabled = json.loads(setting.value) if setting else False
    
    # Use DB values if set, otherwise fall back to env vars
    api_key = db_api_key or settings.codex_api_key or None
    contribute_enabled = db_contribute_enabled or settings.codex_contribute_enabled
    
    return contribute_enabled, api_key


async def sync_product_from_codex(
    db: AsyncSession,
    product: Product,
    overwrite_existing: bool = False,
) -> dict[str, Any]:
    """
    Sync a single product's metadata from Codex.

    Args:
        db: Database session
        product: Product to sync
        overwrite_existing: If True, overwrite existing metadata

    Returns:
        Dict with sync results
    """
    # Read API key from DB so we use the real API, not mock mode
    _, api_key = await get_codex_settings_from_db(db)
    client = get_codex_client(api_key=api_key)
    
    if not await client.is_available():
        return {"synced": False, "reason": "Codex unavailable"}
    
    # Try hash lookup first (most accurate), then fall back to title.
    # A lookup that could not be made is reported as such rather than being
    # read as "Codex does not have this" — see CodexLookupError.
    try:
        match = await client.identify_by_hash(product.file_hash)

        if not match or not match.product:
            match = await client.identify_by_title(
                title=product.title or product.file_name,
                filename=product.file_name,
            )
    except CodexLookupError as e:
        return {"synced": False, "reason": "lookup_failed", "detail": str(e)}


    if not match or not match.product:
        return {"synced": False, "reason": "No match found in Codex"}

    # ⚠️ Only an exact match auto-applies. A fuzzy match is a guess, and
    # applying one overwrites a real product with a different product's
    # metadata: local "Zombie Reign" (Angry Engine Games) matched Codex's
    # "SoRoPlay GamTools Zine: Zombie Ref" (Ken Wickham) at 0.818 and was
    # about to be renamed to it.
    #
    # No confidence floor would be safe here instead. 0.818 is not a low
    # score, and the title fallback is the *normal* path rather than the
    # exceptional one - Codex's catalogue carries almost no file_hashes, so
    # hash lookup misses and nearly every product reaches this branch.
    # Returned as a suggestion so a caller can offer it; never written.
    if match.match_type != MatchType.EXACT:
        return {
            "synced": False,
            "reason": "fuzzy_match_not_applied",
            "product_id": product.id,
            "codex_id": match.product.id,
            "match_type": match.match_type.value,
            "confidence": match.confidence,
            "suggested_title": match.product.title,
        }

    codex_product = match.product
    updated_fields = []
    
    # Update fields if empty or overwrite is enabled
    field_mappings = [
        ("title", codex_product.title),
        ("publisher", codex_product.publisher),
        ("game_system", codex_product.game_system),
        ("product_type", codex_product.product_type),
        ("publication_year", codex_product.publication_year),
        ("page_count", codex_product.page_count),
        ("level_range_min", codex_product.level_range_min),
        ("level_range_max", codex_product.level_range_max),
        ("party_size_min", codex_product.party_size_min),
        ("party_size_max", codex_product.party_size_max),
        ("estimated_runtime", codex_product.estimated_runtime),
    ]
    
    for field_name, codex_value in field_mappings:
        if codex_value is None:
            continue

        # Backstop, not the fix. `from_dict` is what flattens Codex's nested
        # objects; this catches the *next* field Codex nests before it reaches
        # a scalar column. Binding a dict raises inside `db.commit()`, which
        # leaves the session inactive and fails every product behind this one
        # — so a reshape should cost one field, not the whole run.
        if not isinstance(codex_value, (str, int, float, bool)):
            logger.warning(
                f"Codex sent a {type(codex_value).__name__} for {field_name!r}; "
                f"skipping it rather than binding it to a scalar column. "
                f"CodexProduct.from_dict probably needs to flatten this field."
            )
            continue

        current_value = getattr(product, field_name, None)

        if overwrite_existing or not current_value:
            setattr(product, field_name, codex_value)
            if current_value != codex_value:
                updated_fields.append(field_name)
    
    if updated_fields:
        product.ai_identified = True
        product.identification_confidence = match.confidence
        product.updated_at = datetime.now(UTC)
        await db.commit()
    
    return {
        "synced": True,
        "product_id": product.id,
        "codex_id": codex_product.id,
        "match_type": match.match_type.value,
        "confidence": match.confidence,
        "updated_fields": updated_fields,
        "source": match.source.value if match.source else None,
    }


async def sync_all_products(
    db: AsyncSession,
    overwrite_existing: bool = False,
    only_unidentified: bool = True,
) -> dict[str, Any]:
    """
    Sync all products with Codex.
    
    Args:
        db: Database session
        overwrite_existing: If True, overwrite existing metadata
        only_unidentified: If True, only sync products without AI identification
        
    Returns:
        Summary of sync results
    """
    # Read API key from DB so we use the real API, not mock mode
    _, api_key = await get_codex_settings_from_db(db)
    client = get_codex_client(api_key=api_key)

    if not await client.is_available():
        return {
            "success": False,
            "reason": "Codex unavailable",
            "synced": 0,
            "failed": 0,
            "skipped": 0,
        }

    # Ids, not instances. `db.rollback()` in the error handler below expires
    # every object in the session — including the products not yet visited —
    # and reloading an expired attribute needs an await that attribute access
    # cannot make, so holding instances across a rollback turns the next
    # product into a MissingGreenlet. Loading each one inside the loop gets a
    # fresh, awaited read whatever happened to the product before it, and
    # keeps a 19,301-product run from holding the whole library in memory.
    query = select(Product.id).where(
        Product.is_duplicate == False,
        Product.is_missing == False,
        Product.is_superseded == False,
    )
    if only_unidentified:
        query = query.where(Product.ai_identified == False)

    result = await db.execute(query)
    product_ids = list(result.scalars().all())
    
    synced = 0
    failed = 0
    skipped = 0
    results = []
    
    for product_id in product_ids:
        product = await db.get(Product, product_id)
        if product is None:  # deleted between the id query and now
            skipped += 1
            continue
        try:
            sync_result = await sync_product_from_codex(
                db=db,
                product=product,
                overwrite_existing=overwrite_existing,
            )
            
            if sync_result.get("synced"):
                synced += 1
                results.append(sync_result)
            else:
                skipped += 1
                
        except Exception as e:
            failed += 1
            # ⚠️ Roll back BEFORE touching `product` again. A failure inside
            # commit() leaves the session inactive: it then refuses lazy
            # loads, so even reading `product.id` for the log message raises
            # PendingRollbackError — out of the `except`, past the loop, and
            # the whole run dies on the first bad row. That ordering is the
            # entire fix; a rollback placed after the logging call does
            # nothing, because it never runs.
            await db.rollback()
            logger.error(f"Error syncing product {product_id}: {e}")
    
    return {
        "success": True,
        "synced": synced,
        "failed": failed,
        "skipped": skipped,
        "total": len(product_ids),
        "results": results[:20],  # Limit detailed results
    }


async def check_for_updates(
    db: AsyncSession,
    product: Product,
) -> dict[str, Any] | None:
    """
    Check if Codex has updated metadata for a product.
    Does not apply changes, just reports differences.
    """
    # Read API key from DB so we use the real API, not mock mode
    _, api_key = await get_codex_settings_from_db(db)
    client = get_codex_client(api_key=api_key)

    if not await client.is_available():
        return None

    try:
        match = await client.identify_by_hash(product.file_hash)
    except CodexLookupError:
        return None  # "we could not check" reads the same as "nothing to report"

    if not match or not match.product:
        return None

    codex_product = match.product
    differences = []
    
    field_mappings = [
        ("title", codex_product.title),
        ("publisher", codex_product.publisher),
        ("game_system", codex_product.game_system),
        ("product_type", codex_product.product_type),
        ("publication_year", codex_product.publication_year),
    ]
    
    for field_name, codex_value in field_mappings:
        if codex_value is None:
            continue
        
        current_value = getattr(product, field_name, None)
        
        if current_value and current_value != codex_value:
            differences.append({
                "field": field_name,
                "local": current_value,
                "codex": codex_value,
            })
    
    if not differences:
        return None
    
    return {
        "product_id": product.id,
        "codex_id": codex_product.id,
        "differences": differences,
    }


def build_contribution_data(product: Product, include_cover: bool = True) -> dict[str, Any]:
    """
    Build comprehensive contribution data from a product.
    
    Args:
        product: Product to build contribution data from
        include_cover: If True, include base64-encoded cover image
        
    Returns:
        Dict with all available metadata for contribution
    """
    from grimoire.services.contribution_service import get_cover_image_base64
    
    contribution_data = {
        # Basic info
        "title": product.title,
        "description": product.description,
        "author": product.author,
        "publisher": product.publisher,
        "publication_year": product.publication_year,
        "publication_date": f"{product.publication_year}-01-01" if product.publication_year else None,
        "page_count": product.page_count,
        
        # Classification
        "game_system": product.game_system,
        "genre": product.genre,
        "product_type": normalize_product_type(product.product_type),
        "setting": product.setting,
        
        # Adventure details
        "level_range_min": product.level_range_min,
        "level_range_max": product.level_range_max,
        "party_size_min": product.party_size_min,
        "party_size_max": product.party_size_max,
        "estimated_runtime": product.estimated_runtime,
        
        # Series info
        "series": product.series,
        "series_order": product.series_order,
        
        # Publication details
        "format": product.format,
        "isbn": product.isbn,
        "msrp": product.msrp,
        
        # Marketplace links
        "dtrpg_url": product.dtrpg_url,
        "itch_url": product.itch_url,
        
        # Metadata (JSON arrays stored as strings, convert to arrays)
        "themes": _parse_json_array(product.themes),
        "content_warnings": _parse_json_array(product.content_warnings),
    }
    
    # Serialize tags to JSON array.
    #
    # ⚠️ Only when the relationship is already loaded. `product_tags` is lazy,
    # and a lazy load inside an async session raises MissingGreenlet — which
    # `hasattr` does not catch, because it is not an AttributeError. So the
    # old guard would have taken the whole contribution down rather than
    # skipping the tags. Nothing noticed because no contribution has ever
    # carried tags: of the 37 in the live queue, none has the key, though
    # 1,079 products do have tags. To actually send them, the caller has to
    # load the product with `selectinload(Product.product_tags)` first.
    if "product_tags" not in sa_inspect(product).unloaded and product.product_tags:
        contribution_data["tags"] = [pt.tag.name for pt in product.product_tags]
    
    # Add cover image if available and requested
    if include_cover:
        cover_b64 = get_cover_image_base64(product)
        if cover_b64:
            contribution_data["cover_image_base64"] = cover_b64
    
    # Remove None values and empty lists
    return {k: v for k, v in contribution_data.items() if v is not None and v != []}


async def queue_product_for_contribution(
    db: AsyncSession,
    product: Product,
    submit_immediately: bool = True,
    skip_no_change_check: bool = False,
) -> dict[str, Any]:
    """
    Queue a product for contribution to Codex.
    
    Args:
        db: Database session
        product: Product to contribute
        submit_immediately: If True and Codex is available, submit right away
        skip_no_change_check: If True, skip checking if contribution adds value
        
    Returns:
        Dict with queued status and contribution info
    """
    contribute_enabled, api_key = await get_codex_settings_from_db(db)

    if not api_key:
        return {
            "success": False,
            "reason": "no_api_key",
            "message": "No Codex API key configured",
        }

    # Check if contribution would add value (unless skipped)
    seen_match = None
    match_known = False

    if not skip_no_change_check:
        codex = get_codex_client()
        if await codex.is_available():
            def _capture(m):
                nonlocal seen_match, match_known
                seen_match, match_known = m, True

            should, reason = await should_contribute(product, codex, on_match=_capture)
            if not should:
                logger.debug(f"Skipping contribution for product {product.id}: {reason}")
                return {
                    "success": False,
                    "reason": "no_new_data",
                    "message": "Product already has complete data in Codex",
                }
    
    # Check if already contributed (has pending or submitted contribution)
    existing_query = select(ContributionQueue).where(
        ContributionQueue.product_id == product.id,
        ContributionQueue.status.in_([ContributionStatus.PENDING, ContributionStatus.SUBMITTED])
    )
    existing_result = await db.execute(existing_query)
    existing = existing_result.scalar_one_or_none()
    
    if existing:
        return {
            "success": False,
            "reason": "already_queued",
            "message": "Product already has a pending contribution",
            "contribution_id": existing.id,
            "status": existing.status.value,
        }
    
    # Build contribution data from product
    include_cover = await resolve_include_cover(
        product, get_codex_client(api_key=api_key), seen_match, match_known
    )
    contribution_data = build_contribution_data(product, include_cover=include_cover)
    
    if not contribution_data.get("title"):
        return {
            "success": False,
            "reason": "no_title",
            "message": "Product must have a title to contribute",
        }

    # ⚠️ Don't re-send a payload Codex has already rejected. Once polling can
    # write REJECTED, nothing else stops the next sync queueing the identical
    # data for Codex to reject again, every sync, forever — each round leaving
    # another rejected row in somebody's moderation queue. Codex's own
    # duplicate_pending cannot help here: a rejected contribution is no longer
    # PENDING. A rejection is about the data, so changing the data clears it.
    #
    # Compared here rather than at the top of the function because the
    # comparison has to hash the payload as actually built, and building it
    # twice would mean touching `product.product_tags` twice — a lazy
    # relationship load, which raises MissingGreenlet in an async session.
    rejected = (await db.execute(
        select(ContributionQueue)
        .where(
            ContributionQueue.product_id == product.id,
            ContributionQueue.status == ContributionStatus.REJECTED,
        )
        .order_by(ContributionQueue.created_at.desc())
    )).scalars().first()

    if rejected and rejected.payload_hash:
        current_hash = hashlib.sha256(
            json.dumps(contribution_data, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if current_hash == rejected.payload_hash:
            return {
                "success": False,
                "reason": "rejected_unchanged",
                "message": (
                    "Codex rejected this contribution and the local data has not "
                    "changed since. Edit the product to offer it again."
                ),
                "contribution_id": rejected.id,
            }

    # Queue the contribution. The eligibility guard lives inside
    # queue_contribution rather than here, so that `skip_no_change_check=True`
    # cannot get an ineligible product past it — this call site only has to
    # turn the refusal into a result.
    try:
        contribution = await queue_contribution(
            db=db,
            product_id=product.id,
            contribution_data=contribution_data,
            file_hash=product.file_hash,
        )
    except CodexIneligibleError as e:
        return {
            "success": False,
            "reason": e.reason,
            "message": "This product is not eligible to be shared with Codex",
        }
    
    result = {
        "success": True,
        "queued": True,
        "contribution_id": contribution.id,
        "status": contribution.status.value,
    }
    
    # Try to submit immediately if requested
    if submit_immediately:
        from grimoire.services.contribution_service import submit_contribution
        # Always try to submit - the submit_contribution uses its own client with the API key
        submitted = await submit_contribution(db, contribution, api_key)
        await db.refresh(contribution)
        result["submitted"] = submitted
        result["status"] = contribution.status.value
        if contribution.error_message:
            result["error_message"] = contribution.error_message
    
    return result


async def queue_local_edit_for_sync(
    db: AsyncSession,
    product: Product,
    edited_fields: dict[str, Any],
) -> ContributionQueue | None:
    """
    Queue a local edit to be synced back to Codex when reconnected.
    Only queues if contribute is enabled and user has API key.
    
    Args:
        db: Database session
        product: Product that was edited
        edited_fields: Dict of field names to new values
        
    Returns:
        ContributionQueue entry if queued, None otherwise
    """
    # Get settings from database (where frontend saves them)
    contribute_enabled, api_key = await get_codex_settings_from_db(db)
    
    if not contribute_enabled:
        logger.debug("Codex contributions disabled, not queuing edit")
        return None
    
    if not api_key:
        logger.debug("No Codex API key configured, not queuing edit")
        return None
    
    # Build contribution data from product + edits. Same cover rules as the
    # queue path — a locally-edited scan must not upload its artwork either.
    include_cover = await resolve_include_cover(
        product, get_codex_client(api_key=api_key)
    )
    contribution_data = build_contribution_data(product, include_cover=include_cover)
    
    # Apply the edits
    contribution_data.update(edited_fields)
    
    # Remove None values again after update
    contribution_data = {k: v for k, v in contribution_data.items() if v is not None}
    
    return await queue_contribution(
        db=db,
        product_id=product.id,
        contribution_data=contribution_data,
        file_hash=product.file_hash,
    )


async def sync_pending_contributions(
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Attempt to sync all pending contributions to Codex.
    Called when connectivity is restored or on a schedule.
    
    Returns:
        Summary of sync results
    """
    # Get settings from database (where frontend saves them)
    contribute_enabled, api_key = await get_codex_settings_from_db(db)
    
    if not api_key:
        return {
            "success": False,
            "reason": "No API key configured",
            "submitted": 0,
            "failed": 0,
        }
    
    # Create a client with the API key to check availability
    from grimoire.services.codex import CodexClient
    client = CodexClient(api_key=api_key, use_mock=False)
    
    if not await client.is_available():
        return {
            "success": False,
            "reason": "Codex unavailable",
            "submitted": 0,
            "failed": 0,
        }
    
    return await submit_all_pending(
        db=db,
        api_key=api_key,
    )


async def get_sync_status(db: AsyncSession) -> dict[str, Any]:
    """
    Get overall sync status including pending contributions.
    """
    # Get settings from database (where frontend saves them)
    contribute_enabled, api_key = await get_codex_settings_from_db(db)
    
    # Create a client with the API key to check availability
    from grimoire.services.codex import CodexClient
    client = CodexClient(api_key=api_key, use_mock=False) if api_key else get_codex_client()
    codex_available = await client.is_available()
    
    # Count pending contributions
    query = select(ContributionQueue).where(
        ContributionQueue.status == ContributionStatus.PENDING
    )
    result = await db.execute(query)
    pending = list(result.scalars().all())
    
    return {
        "codex_available": codex_available,
        "codex_mock_mode": client.use_mock,
        "contribute_enabled": contribute_enabled,
        "has_api_key": bool(api_key),
        "pending_contributions": len(pending),
        "can_sync": codex_available and bool(api_key) and len(pending) > 0,
    }
