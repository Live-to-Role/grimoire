"""Service for managing Codex contribution queue."""

import base64
import json
import logging
from datetime import datetime, UTC
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import ContributionQueue, ContributionStatus, Product
from grimoire.services.codex import CodexClient, ContributionResult, get_codex_client

logger = logging.getLogger(__name__)

# Maximum cover image size for contribution (in bytes)
MAX_COVER_SIZE_BYTES = 500 * 1024  # 500 KB


def get_cover_image_base64(product: Product, max_size_bytes: int = MAX_COVER_SIZE_BYTES) -> str | None:
    """
    Get product's cover image as base64 for contribution to Codex.
    
    Args:
        product: Product with cover_image_path
        max_size_bytes: Maximum size in bytes (default 500KB)
        
    Returns:
        Base64-encoded JPEG string, or None if unavailable/too large
    """
    if not product.cover_extracted or not product.cover_image_path:
        return None
    
    cover_path = Path(product.cover_image_path)
    if not cover_path.exists():
        logger.debug(f"Cover file not found: {cover_path}")
        return None
    
    try:
        # Read original file
        with open(cover_path, "rb") as f:
            data = f.read()
        
        # If already under limit, return as-is
        if len(data) <= max_size_bytes:
            return base64.b64encode(data).decode("utf-8")
        
        # Re-compress with progressively lower quality
        img = Image.open(cover_path)
        
        # Convert to RGB if necessary (handles RGBA, palette modes)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        
        buffer = BytesIO()
        quality = 75
        
        while quality >= 20:
            buffer.seek(0)
            buffer.truncate()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            
            if buffer.tell() <= max_size_bytes:
                logger.debug(f"Compressed cover to {buffer.tell()} bytes at quality {quality}")
                return base64.b64encode(buffer.getvalue()).decode("utf-8")
            
            quality -= 10
        
        # Still too large even at lowest quality - try resizing
        width, height = img.size
        scale = 0.75
        
        while scale >= 0.25:
            new_size = (int(width * scale), int(height * scale))
            resized = img.resize(new_size, Image.Resampling.LANCZOS)
            
            buffer.seek(0)
            buffer.truncate()
            resized.save(buffer, format="JPEG", quality=60, optimize=True)
            
            if buffer.tell() <= max_size_bytes:
                logger.debug(f"Resized cover to {new_size} at {buffer.tell()} bytes")
                return base64.b64encode(buffer.getvalue()).decode("utf-8")
            
            scale -= 0.25
        
        logger.warning(f"Could not compress cover to under {max_size_bytes} bytes: {cover_path}")
        return None
        
    except Exception as e:
        logger.warning(f"Error encoding cover image {cover_path}: {e}")
        return None


async def queue_contribution(
    db: AsyncSession,
    product_id: int,
    contribution_data: dict[str, Any],
    file_hash: str | None = None,
) -> ContributionQueue:
    """
    Queue a contribution for submission to Codex.
    Used when offline or when user wants to review before submitting.
    """
    contribution = ContributionQueue(
        product_id=product_id,
        contribution_data=json.dumps(contribution_data),
        file_hash=file_hash,
        status=ContributionStatus.PENDING,
    )
    db.add(contribution)
    await db.commit()
    await db.refresh(contribution)
    
    logger.info(f"Queued contribution for product {product_id}")
    return contribution


async def get_pending_contributions(db: AsyncSession) -> list[ContributionQueue]:
    """Get all pending contributions."""
    query = select(ContributionQueue).where(
        ContributionQueue.status == ContributionStatus.PENDING
    ).order_by(ContributionQueue.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def submit_contribution(
    db: AsyncSession,
    contribution: ContributionQueue,
    api_key: str,
) -> bool:
    """
    Submit a single contribution to Codex.
    Returns True if successful.
    """
    codex = CodexClient(api_key=api_key, use_mock=False)
    
    contribution.attempts += 1
    contribution.last_attempt_at = datetime.now(UTC)
    
    try:
        data = json.loads(contribution.contribution_data)
        result = await codex.contribute(data, contribution.file_hash)
        
        if result.success:
            contribution.status = ContributionStatus.SUBMITTED
            contribution.error_message = None
            logger.info(
                f"Successfully submitted contribution {contribution.id}: "
                f"status={result.status}, product_id={result.product_id or result.contribution_id}"
            )
        else:
            contribution.status = ContributionStatus.FAILED
            contribution.error_message = result.reason or "Submission failed"
            logger.warning(f"Failed to submit contribution {contribution.id}: {result.reason}")
        
        await db.commit()
        return result.success
        
    except Exception as e:
        contribution.status = ContributionStatus.FAILED
        contribution.error_message = str(e)[:500]
        await db.commit()
        logger.error(f"Error submitting contribution {contribution.id}: {e}")
        return False


async def submit_all_pending(
    db: AsyncSession,
    api_key: str,
    max_attempts: int = 3,
) -> dict[str, int]:
    """
    Submit all pending contributions to Codex.
    Returns counts of submitted, failed, and skipped.
    """
    pending = await get_pending_contributions(db)
    
    submitted = 0
    failed = 0
    skipped = 0
    
    for contribution in pending:
        if contribution.attempts >= max_attempts:
            skipped += 1
            continue
        
        success = await submit_contribution(db, contribution, api_key)
        if success:
            submitted += 1
        else:
            failed += 1
    
    return {
        "submitted": submitted,
        "failed": failed,
        "skipped": skipped,
        "total": len(pending),
    }


async def get_contribution_stats(db: AsyncSession) -> dict[str, int]:
    """Get contribution queue statistics."""
    query = select(ContributionQueue)
    result = await db.execute(query)
    contributions = list(result.scalars().all())
    
    stats = {
        "pending": 0,
        "submitted": 0,
        "accepted": 0,
        "rejected": 0,
        "failed": 0,
        "total": len(contributions),
    }
    
    for c in contributions:
        stats[c.status.value] = stats.get(c.status.value, 0) + 1
    
    return stats


async def cancel_contribution(
    db: AsyncSession,
    contribution_id: int,
) -> bool:
    """Cancel a pending contribution."""
    query = select(ContributionQueue).where(ContributionQueue.id == contribution_id)
    result = await db.execute(query)
    contribution = result.scalar_one_or_none()
    
    if not contribution:
        return False
    
    if contribution.status != ContributionStatus.PENDING:
        return False
    
    await db.delete(contribution)
    await db.commit()
    return True
