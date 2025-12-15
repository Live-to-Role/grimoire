"""Contribution queue API endpoints."""

import json
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from grimoire.api.deps import DbSession
from grimoire.models import ContributionQueue, ContributionStatus, Product
from grimoire.services.contribution_service import (
    queue_contribution,
    get_pending_contributions,
    submit_all_pending,
    get_contribution_stats,
    cancel_contribution,
)
from grimoire.services.contribution_queue_processor import (
    get_queue_processor,
)


router = APIRouter()


class QueueContributionRequest(BaseModel):
    """Request to queue a contribution."""
    product_id: int
    contribution_data: dict
    file_hash: str | None = None


class SubmitContributionsRequest(BaseModel):
    """Request to submit pending contributions."""
    api_key: str = Field(..., description="Codex API key")
    max_attempts: int = Field(3, description="Max retry attempts per contribution")


@router.get("")
async def list_contributions(
    db: DbSession,
    status: str | None = None,
) -> dict:
    """List all contributions, optionally filtered by status."""
    query = select(ContributionQueue).order_by(ContributionQueue.created_at.desc())
    
    if status:
        try:
            status_enum = ContributionStatus(status)
            query = query.where(ContributionQueue.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    result = await db.execute(query)
    contributions = list(result.scalars().all())
    
    return {
        "contributions": [
            {
                "id": c.id,
                "product_id": c.product_id,
                "status": c.status.value,
                "contribution_data": json.loads(c.contribution_data),
                "file_hash": c.file_hash,
                "attempts": c.attempts,
                "last_attempt_at": c.last_attempt_at.isoformat() if c.last_attempt_at else None,
                "error_message": c.error_message,
                "created_at": c.created_at.isoformat(),
            }
            for c in contributions
        ],
        "total": len(contributions),
    }


@router.get("/stats")
async def contributions_stats(db: DbSession) -> dict:
    """Get contribution queue statistics."""
    return await get_contribution_stats(db)


@router.post("")
async def create_contribution(
    db: DbSession,
    request: QueueContributionRequest,
) -> dict:
    """Queue a new contribution for Codex."""
    # Verify product exists
    product_query = select(Product).where(Product.id == request.product_id)
    product_result = await db.execute(product_query)
    product = product_result.scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    contribution = await queue_contribution(
        db=db,
        product_id=request.product_id,
        contribution_data=request.contribution_data,
        file_hash=request.file_hash or product.file_hash,
    )
    
    return {
        "id": contribution.id,
        "product_id": contribution.product_id,
        "status": contribution.status.value,
        "created_at": contribution.created_at.isoformat(),
    }


@router.post("/submit")
async def submit_contributions(
    db: DbSession,
    request: SubmitContributionsRequest,
) -> dict:
    """Submit all pending contributions to Codex."""
    results = await submit_all_pending(
        db=db,
        api_key=request.api_key,
        max_attempts=request.max_attempts,
    )
    return results


@router.post("/product/{product_id}")
async def contribute_product(
    db: DbSession,
    product_id: int,
) -> dict:
    """
    Queue a product for contribution to Codex.
    This is the simple endpoint - just provide the product ID and it will
    build the contribution data from the product's current metadata.
    """
    from grimoire.services.sync_service import queue_product_for_contribution
    
    product_query = select(Product).where(Product.id == product_id)
    product_result = await db.execute(product_query)
    product = product_result.scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    result = await queue_product_for_contribution(db, product, submit_immediately=True)
    
    if not result["success"]:
        if result["reason"] == "no_api_key":
            raise HTTPException(status_code=400, detail="No Codex API key configured")
        elif result["reason"] == "no_title":
            raise HTTPException(status_code=400, detail="Product must have a title to contribute")
    
    return result


@router.get("/product/{product_id}/status")
async def get_product_contribution_status(
    db: DbSession,
    product_id: int,
) -> dict:
    """Get the contribution status for a specific product."""
    query = select(ContributionQueue).where(
        ContributionQueue.product_id == product_id
    ).order_by(ContributionQueue.created_at.desc())
    
    result = await db.execute(query)
    contributions = list(result.scalars().all())
    
    if not contributions:
        return {
            "has_contribution": False,
            "product_id": product_id,
        }
    
    latest = contributions[0]
    return {
        "has_contribution": True,
        "product_id": product_id,
        "contribution_id": latest.id,
        "status": latest.status.value,
        "created_at": latest.created_at.isoformat(),
        "submitted_at": latest.last_attempt_at.isoformat() if latest.last_attempt_at else None,
        "error_message": latest.error_message,
    }


@router.delete("/{contribution_id}")
async def delete_contribution(
    db: DbSession,
    contribution_id: int,
) -> dict:
    """Cancel/delete a pending contribution."""
    success = await cancel_contribution(db, contribution_id)
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Contribution not found or not in pending status"
        )
    
    return {"deleted": True, "id": contribution_id}


@router.get("/queue/status")
async def get_queue_processor_status(db: DbSession) -> dict:
    """
    Get the background queue processor status.
    
    Returns processor state and statistics about submissions.
    """
    processor = get_queue_processor()
    stats = processor.get_stats()
    
    # Also get queue counts from database
    queue_stats = await get_contribution_stats(db)
    
    return {
        "processor": stats,
        "queue": queue_stats,
    }
