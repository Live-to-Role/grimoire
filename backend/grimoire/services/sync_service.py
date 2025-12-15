"""Service for syncing metadata with Codex."""

import json
import logging
from datetime import datetime, UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.config import settings
from grimoire.models import Product, ContributionQueue, ContributionStatus
from grimoire.services.codex import CodexProduct, get_codex_client, IdentificationSource
from grimoire.services.contribution_service import queue_contribution, submit_all_pending

logger = logging.getLogger(__name__)


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
    if not settings.codex_contribute_enabled:
        logger.debug("Codex contributions disabled, not queuing edit")
        return None
    
    if not settings.codex_api_key:
        logger.debug("No Codex API key configured, not queuing edit")
        return None
    
    # Build contribution data from product + edits
    contribution_data = {
        "title": product.title,
        "publisher": product.publisher,
        "game_system": product.game_system,
        "product_type": product.product_type,
        "publication_year": product.publication_year,
        "page_count": product.page_count,
        "level_range_min": product.level_range_min,
        "level_range_max": product.level_range_max,
        "party_size_min": product.party_size_min,
        "party_size_max": product.party_size_max,
        "estimated_runtime": product.estimated_runtime,
    }
    
    # Apply the edits
    contribution_data.update(edited_fields)
    
    # Remove None values
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
    if not settings.codex_api_key:
        return {
            "success": False,
            "reason": "No API key configured",
            "submitted": 0,
            "failed": 0,
        }
    
    client = get_codex_client()
    
    if not await client.is_available():
        return {
            "success": False,
            "reason": "Codex unavailable",
            "submitted": 0,
            "failed": 0,
        }
    
    return await submit_all_pending(
        db=db,
        api_key=settings.codex_api_key,
    )


async def get_sync_status(db: AsyncSession) -> dict[str, Any]:
    """
    Get overall sync status including pending contributions.
    """
    client = get_codex_client()
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
        "contribute_enabled": settings.codex_contribute_enabled,
        "has_api_key": bool(settings.codex_api_key),
        "pending_contributions": len(pending),
        "can_sync": codex_available and bool(settings.codex_api_key) and len(pending) > 0,
    }
