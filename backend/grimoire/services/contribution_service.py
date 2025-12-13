"""Service for managing Codex contribution queue."""

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import ContributionQueue, ContributionStatus, Product
from grimoire.services.codex import CodexClient, get_codex_client

logger = logging.getLogger(__name__)


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
    contribution.last_attempt_at = datetime.utcnow()
    
    try:
        data = json.loads(contribution.contribution_data)
        success = await codex.contribute(data, contribution.file_hash)
        
        if success:
            contribution.status = ContributionStatus.SUBMITTED
            contribution.error_message = None
            logger.info(f"Successfully submitted contribution {contribution.id}")
        else:
            contribution.status = ContributionStatus.FAILED
            contribution.error_message = "Submission returned false"
            logger.warning(f"Failed to submit contribution {contribution.id}")
        
        await db.commit()
        return success
        
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
