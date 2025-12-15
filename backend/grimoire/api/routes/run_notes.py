"""Run Notes API endpoints."""

from datetime import datetime, UTC

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from grimoire.api.deps import DbSession
from grimoire.models import Product, RunNote, Campaign

router = APIRouter()


class RunNoteCreate(BaseModel):
    """Request to create a run note."""
    note_type: str  # prep_tip, modification, warning, review
    title: str
    content: str
    spoiler_level: str = "none"  # none, minor, major, endgame
    campaign_id: int | None = None
    visibility: str = "private"  # private, anonymous, public


class RunNoteUpdate(BaseModel):
    """Request to update a run note."""
    note_type: str | None = None
    title: str | None = None
    content: str | None = None
    spoiler_level: str | None = None
    visibility: str | None = None


class RunNoteResponse(BaseModel):
    """Response for a run note."""
    id: int
    product_id: int
    campaign_id: int | None
    note_type: str
    title: str
    content: str
    spoiler_level: str
    shared_to_codex: bool
    codex_note_id: str | None
    visibility: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def validate_note_type(note_type: str) -> None:
    """Validate note type value."""
    valid_types = {"prep_tip", "modification", "warning", "review"}
    if note_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid note_type. Must be one of: {valid_types}"
        )


def validate_spoiler_level(spoiler_level: str) -> None:
    """Validate spoiler level value."""
    valid_levels = {"none", "minor", "major", "endgame"}
    if spoiler_level not in valid_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid spoiler_level. Must be one of: {valid_levels}"
        )


def validate_visibility(visibility: str) -> None:
    """Validate visibility value."""
    valid_values = {"private", "anonymous", "public"}
    if visibility not in valid_values:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid visibility. Must be one of: {valid_values}"
        )


@router.get("/products/{product_id}/run-notes")
async def list_product_run_notes(
    db: DbSession,
    product_id: int,
    note_type: str | None = Query(None, description="Filter by note type"),
    spoiler_level: str | None = Query(None, description="Max spoiler level to show"),
) -> list[RunNoteResponse]:
    """List run notes for a product."""
    # Verify product exists
    product_query = select(Product).where(Product.id == product_id)
    product_result = await db.execute(product_query)
    if not product_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")

    query = select(RunNote).where(RunNote.product_id == product_id)

    if note_type:
        validate_note_type(note_type)
        query = query.where(RunNote.note_type == note_type)

    # Filter by max spoiler level
    if spoiler_level:
        validate_spoiler_level(spoiler_level)
        spoiler_order = {"none": 0, "minor": 1, "major": 2, "endgame": 3}
        max_level = spoiler_order.get(spoiler_level, 3)
        allowed_levels = [k for k, v in spoiler_order.items() if v <= max_level]
        query = query.where(RunNote.spoiler_level.in_(allowed_levels))

    query = query.order_by(RunNote.created_at.desc())

    result = await db.execute(query)
    notes = result.scalars().all()

    return [RunNoteResponse.model_validate(note) for note in notes]


@router.post("/products/{product_id}/run-notes")
async def create_run_note(
    db: DbSession,
    product_id: int,
    request: RunNoteCreate,
) -> RunNoteResponse:
    """Create a run note for a product."""
    # Verify product exists
    product_query = select(Product).where(Product.id == product_id)
    product_result = await db.execute(product_query)
    if not product_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")

    # Validate fields
    validate_note_type(request.note_type)
    validate_spoiler_level(request.spoiler_level)
    validate_visibility(request.visibility)

    # Verify campaign exists if provided
    if request.campaign_id:
        campaign_query = select(Campaign).where(Campaign.id == request.campaign_id)
        campaign_result = await db.execute(campaign_query)
        if not campaign_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Campaign not found")

    note = RunNote(
        product_id=product_id,
        campaign_id=request.campaign_id,
        note_type=request.note_type,
        title=request.title,
        content=request.content,
        spoiler_level=request.spoiler_level,
        visibility=request.visibility,
    )

    db.add(note)
    await db.commit()
    await db.refresh(note)

    return RunNoteResponse.model_validate(note)


@router.get("/run-notes/{note_id}")
async def get_run_note(
    db: DbSession,
    note_id: int,
) -> RunNoteResponse:
    """Get a specific run note."""
    query = select(RunNote).where(RunNote.id == note_id)
    result = await db.execute(query)
    note = result.scalar_one_or_none()

    if not note:
        raise HTTPException(status_code=404, detail="Run note not found")

    return RunNoteResponse.model_validate(note)


@router.put("/run-notes/{note_id}")
async def update_run_note(
    db: DbSession,
    note_id: int,
    request: RunNoteUpdate,
) -> RunNoteResponse:
    """Update a run note."""
    query = select(RunNote).where(RunNote.id == note_id)
    result = await db.execute(query)
    note = result.scalar_one_or_none()

    if not note:
        raise HTTPException(status_code=404, detail="Run note not found")

    if request.note_type is not None:
        validate_note_type(request.note_type)
        note.note_type = request.note_type

    if request.title is not None:
        note.title = request.title

    if request.content is not None:
        note.content = request.content

    if request.spoiler_level is not None:
        validate_spoiler_level(request.spoiler_level)
        note.spoiler_level = request.spoiler_level

    if request.visibility is not None:
        validate_visibility(request.visibility)
        note.visibility = request.visibility

    note.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(note)

    return RunNoteResponse.model_validate(note)


@router.delete("/run-notes/{note_id}")
async def delete_run_note(
    db: DbSession,
    note_id: int,
) -> dict:
    """Delete a run note."""
    query = select(RunNote).where(RunNote.id == note_id)
    result = await db.execute(query)
    note = result.scalar_one_or_none()

    if not note:
        raise HTTPException(status_code=404, detail="Run note not found")

    await db.delete(note)
    await db.commit()

    return {"id": note_id, "deleted": True}


@router.post("/run-notes/{note_id}/share")
async def share_run_note_to_codex(
    db: DbSession,
    note_id: int,
) -> dict:
    """Share a run note to Codex (placeholder - actual sync requires Codex integration)."""
    query = select(RunNote).where(RunNote.id == note_id)
    result = await db.execute(query)
    note = result.scalar_one_or_none()

    if not note:
        raise HTTPException(status_code=404, detail="Run note not found")

    if note.visibility == "private":
        raise HTTPException(
            status_code=400,
            detail="Cannot share private notes. Change visibility to anonymous or public first."
        )

    if note.shared_to_codex:
        raise HTTPException(status_code=400, detail="Note already shared to Codex")

    # TODO: Actual Codex API integration
    # For now, just mark as shared (placeholder)
    note.shared_to_codex = True
    note.codex_note_id = f"placeholder_{note.id}"  # Would be real ID from Codex

    await db.commit()

    return {
        "id": note.id,
        "shared": True,
        "codex_note_id": note.codex_note_id,
        "message": "Note marked for sharing. Codex sync not yet implemented.",
    }
