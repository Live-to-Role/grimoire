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
