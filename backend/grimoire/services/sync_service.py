"""Service for syncing metadata with Codex."""

import json
import logging
from datetime import datetime, UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.config import settings
from grimoire.models import Product, ContributionQueue, ContributionStatus, Setting
from grimoire.services.codex import CodexClient, CodexProduct, get_codex_client, IdentificationSource
from grimoire.services.contribution_service import queue_contribution, submit_all_pending

logger = logging.getLogger(__name__)

# Fields that Codex tracks - used for no-change detection
CONTRIBUTION_FIELDS = [
    "publisher", "author", "game_system", "genre", "product_type",
    "publication_year", "page_count", "level_range_min", "level_range_max",
    "party_size_min", "party_size_max", "estimated_runtime",
]


async def should_contribute(
    product: Product,
    codex_client: CodexClient,
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
    
    # Try to find existing product in Codex by hash
    match = await codex_client.identify_by_hash(product.file_hash)
    
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
    client = get_codex_client()
    
    if not await client.is_available():
        return {"synced": False, "reason": "Codex unavailable"}
    
    # Try hash lookup first (most accurate)
    match = await client.identify_by_hash(product.file_hash)
    
    if not match or not match.product:
        # Fall back to title lookup
        match = await client.identify_by_title(
            title=product.title or product.file_name,
            filename=product.file_name,
        )
    
    if not match or not match.product:
        return {"synced": False, "reason": "No match found in Codex"}
    
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
    client = get_codex_client()
    
    if not await client.is_available():
        return {
            "success": False,
            "reason": "Codex unavailable",
            "synced": 0,
            "failed": 0,
            "skipped": 0,
        }
    
    query = select(Product)
    if only_unidentified:
        query = query.where(Product.ai_identified == False)
    
    result = await db.execute(query)
    products = list(result.scalars().all())
    
    synced = 0
    failed = 0
    skipped = 0
    results = []
    
    for product in products:
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
            logger.error(f"Error syncing product {product.id}: {e}")
            failed += 1
    
    return {
        "success": True,
        "synced": synced,
        "failed": failed,
        "skipped": skipped,
        "total": len(products),
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
    client = get_codex_client()
    
    if not await client.is_available():
        return None
    
    match = await client.identify_by_hash(product.file_hash)
    
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
        "title": product.title,
        "publisher": product.publisher,
        "author": product.author,
        "game_system": product.game_system,
        "genre": product.genre,
        "product_type": product.product_type,
        "publication_year": product.publication_year,
        "page_count": product.page_count,
        "level_range_min": product.level_range_min,
        "level_range_max": product.level_range_max,
        "party_size_min": product.party_size_min,
        "party_size_max": product.party_size_max,
        "estimated_runtime": product.estimated_runtime,
    }
    
    # Add cover image if available and requested
    if include_cover:
        cover_b64 = get_cover_image_base64(product)
        if cover_b64:
            contribution_data["cover_image"] = cover_b64
    
    # Remove None values
    return {k: v for k, v in contribution_data.items() if v is not None}


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
    if not skip_no_change_check:
        codex = get_codex_client()
        if await codex.is_available():
            should, reason = await should_contribute(product, codex)
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
    contribution_data = build_contribution_data(product)
    
    if not contribution_data.get("title"):
        return {
            "success": False,
            "reason": "no_title",
            "message": "Product must have a title to contribute",
        }
    
    # Queue the contribution
    contribution = await queue_contribution(
        db=db,
        product_id=product.id,
        contribution_data=contribution_data,
        file_hash=product.file_hash,
    )
    
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
    
    # Build contribution data from product + edits
    contribution_data = build_contribution_data(product)
    
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
