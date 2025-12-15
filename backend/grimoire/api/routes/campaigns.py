"""Campaign management API endpoints."""

from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from grimoire.api.deps import DbSession
from grimoire.models import Campaign, Session, Product
from grimoire.models.campaign import campaign_products


router = APIRouter()


class CampaignCreate(BaseModel):
    """Request to create a campaign."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    game_system: str | None = None
    status: str = Field("active")
    start_date: datetime | None = None
    player_count: int | None = None
    notes: str | None = None


class CampaignUpdate(BaseModel):
    """Request to update a campaign."""
    name: str | None = None
    description: str | None = None
    game_system: str | None = None
    status: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    player_count: int | None = None
    notes: str | None = None


class SessionCreate(BaseModel):
    """Request to create a session."""
    title: str | None = None
    scheduled_date: datetime | None = None
    notes: str | None = None


class SessionUpdate(BaseModel):
    """Request to update a session."""
    title: str | None = None
    scheduled_date: datetime | None = None
    actual_date: datetime | None = None
    duration_minutes: int | None = None
    summary: str | None = None
    notes: str | None = None
    status: str | None = None


@router.get("")
async def list_campaigns(
    db: DbSession,
    status: str | None = Query(None),
    game_system: str | None = Query(None),
) -> dict:
    """List all campaigns."""
    query = select(Campaign)
    
    if status:
        query = query.where(Campaign.status == status)
    if game_system:
        query = query.where(Campaign.game_system == game_system)
    
    query = query.order_by(Campaign.updated_at.desc())
    
    result = await db.execute(query)
    campaigns = result.scalars().all()

    return {
        "campaigns": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "game_system": c.game_system,
                "status": c.status,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "player_count": c.player_count,
                "session_count": c.session_count,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in campaigns
        ],
        "total": len(campaigns),
    }


@router.post("")
async def create_campaign(
    db: DbSession,
    request: CampaignCreate,
) -> dict:
    """Create a new campaign."""
    campaign = Campaign(
        name=request.name,
        description=request.description,
        game_system=request.game_system,
        status=request.status,
        start_date=request.start_date,
        player_count=request.player_count,
        notes=request.notes,
    )
    
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    return {
        "id": campaign.id,
        "name": campaign.name,
        "status": campaign.status,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
    }


@router.get("/{campaign_id}")
async def get_campaign(
    db: DbSession,
    campaign_id: int,
) -> dict:
    """Get a campaign with its products and sessions."""
    query = select(Campaign).where(Campaign.id == campaign_id).options(
        selectinload(Campaign.products),
        selectinload(Campaign.sessions),
    )
    result = await db.execute(query)
    campaign = result.scalar_one_or_none()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return {
        "id": campaign.id,
        "name": campaign.name,
        "description": campaign.description,
        "game_system": campaign.game_system,
        "status": campaign.status,
        "start_date": campaign.start_date.isoformat() if campaign.start_date else None,
        "end_date": campaign.end_date.isoformat() if campaign.end_date else None,
        "player_count": campaign.player_count,
        "session_count": campaign.session_count,
        "notes": campaign.notes,
        "products": [
            {
                "id": p.id,
                "title": p.title or p.file_name,
                "game_system": p.game_system,
                "product_type": p.product_type,
            }
            for p in campaign.products
        ],
        "sessions": [
            {
                "id": s.id,
                "session_number": s.session_number,
                "title": s.title,
                "scheduled_date": s.scheduled_date.isoformat() if s.scheduled_date else None,
                "status": s.status,
            }
            for s in sorted(campaign.sessions, key=lambda x: x.session_number)
        ],
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
    }


@router.put("/{campaign_id}")
async def update_campaign(
    db: DbSession,
    campaign_id: int,
    request: CampaignUpdate,
) -> dict:
    """Update a campaign."""
    query = select(Campaign).where(Campaign.id == campaign_id)
    result = await db.execute(query)
    campaign = result.scalar_one_or_none()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if request.name is not None:
        campaign.name = request.name
    if request.description is not None:
        campaign.description = request.description
    if request.game_system is not None:
        campaign.game_system = request.game_system
    if request.status is not None:
        campaign.status = request.status
    if request.start_date is not None:
        campaign.start_date = request.start_date
    if request.end_date is not None:
        campaign.end_date = request.end_date
    if request.player_count is not None:
        campaign.player_count = request.player_count
    if request.notes is not None:
        campaign.notes = request.notes

    await db.commit()

    return {"id": campaign.id, "updated": True}


@router.delete("/{campaign_id}")
async def delete_campaign(
    db: DbSession,
    campaign_id: int,
) -> dict:
    """Delete a campaign."""
    query = select(Campaign).where(Campaign.id == campaign_id)
    result = await db.execute(query)
    campaign = result.scalar_one_or_none()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    await db.delete(campaign)
    await db.commit()

    return {"deleted": True}


@router.post("/{campaign_id}/products/{product_id}")
async def add_product_to_campaign(
    db: DbSession,
    campaign_id: int,
    product_id: int,
    notes: str | None = None,
) -> dict:
    """Add a product to a campaign."""
    # Verify campaign exists
    campaign_query = select(Campaign).where(Campaign.id == campaign_id)
    campaign_result = await db.execute(campaign_query)
    campaign = campaign_result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Verify product exists
    product_query = select(Product).where(Product.id == product_id)
    product_result = await db.execute(product_query)
    product = product_result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Add to campaign
    stmt = campaign_products.insert().values(
        campaign_id=campaign_id,
        product_id=product_id,
        notes=notes,
    )
    try:
        await db.execute(stmt)
        await db.commit()
    except Exception:
        # Already exists
        pass

    return {"added": True, "campaign_id": campaign_id, "product_id": product_id}


@router.delete("/{campaign_id}/products/{product_id}")
async def remove_product_from_campaign(
    db: DbSession,
    campaign_id: int,
    product_id: int,
) -> dict:
    """Remove a product from a campaign."""
    stmt = campaign_products.delete().where(
        campaign_products.c.campaign_id == campaign_id,
        campaign_products.c.product_id == product_id,
    )
    await db.execute(stmt)
    await db.commit()

    return {"removed": True}


@router.get("/{campaign_id}/sessions")
async def list_sessions(
    db: DbSession,
    campaign_id: int,
) -> dict:
    """List all sessions for a campaign."""
    # Verify campaign exists
    campaign_query = select(Campaign).where(Campaign.id == campaign_id)
    campaign_result = await db.execute(campaign_query)
    campaign = campaign_result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    query = select(Session).where(Session.campaign_id == campaign_id).order_by(Session.session_number)
    result = await db.execute(query)
    sessions = result.scalars().all()

    return {
        "sessions": [
            {
                "id": s.id,
                "campaign_id": s.campaign_id,
                "session_number": s.session_number,
                "title": s.title,
                "scheduled_date": s.scheduled_date.isoformat() if s.scheduled_date else None,
                "actual_date": s.actual_date.isoformat() if s.actual_date else None,
                "status": s.status,
                "summary": s.summary,
            }
            for s in sessions
        ],
        "total": len(sessions),
    }


@router.post("/{campaign_id}/sessions")
async def create_session(
    db: DbSession,
    campaign_id: int,
    request: SessionCreate,
) -> dict:
    """Create a new session for a campaign."""
    # Verify campaign exists
    campaign_query = select(Campaign).where(Campaign.id == campaign_id)
    campaign_result = await db.execute(campaign_query)
    campaign = campaign_result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get next session number
    count_query = select(func.count()).select_from(Session).where(
        Session.campaign_id == campaign_id
    )
    count_result = await db.execute(count_query)
    session_count = count_result.scalar() or 0

    session = Session(
        campaign_id=campaign_id,
        session_number=session_count + 1,
        title=request.title,
        scheduled_date=request.scheduled_date,
        notes=request.notes,
    )

    db.add(session)
    
    # Update campaign session count
    campaign.session_count = session_count + 1
    
    await db.commit()
    await db.refresh(session)

    return {
        "id": session.id,
        "session_number": session.session_number,
        "title": session.title,
        "scheduled_date": session.scheduled_date.isoformat() if session.scheduled_date else None,
    }


@router.get("/{campaign_id}/sessions/{session_id}")
async def get_session(
    db: DbSession,
    campaign_id: int,
    session_id: int,
) -> dict:
    """Get a session."""
    query = select(Session).where(
        Session.id == session_id,
        Session.campaign_id == campaign_id,
    )
    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "id": session.id,
        "campaign_id": session.campaign_id,
        "session_number": session.session_number,
        "title": session.title,
        "scheduled_date": session.scheduled_date.isoformat() if session.scheduled_date else None,
        "actual_date": session.actual_date.isoformat() if session.actual_date else None,
        "duration_minutes": session.duration_minutes,
        "summary": session.summary,
        "notes": session.notes,
        "status": session.status,
    }


@router.put("/{campaign_id}/sessions/{session_id}")
async def update_session(
    db: DbSession,
    campaign_id: int,
    session_id: int,
    request: SessionUpdate,
) -> dict:
    """Update a session."""
    query = select(Session).where(
        Session.id == session_id,
        Session.campaign_id == campaign_id,
    )
    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if request.title is not None:
        session.title = request.title
    if request.scheduled_date is not None:
        session.scheduled_date = request.scheduled_date
    if request.actual_date is not None:
        session.actual_date = request.actual_date
    if request.duration_minutes is not None:
        session.duration_minutes = request.duration_minutes
    if request.summary is not None:
        session.summary = request.summary
    if request.notes is not None:
        session.notes = request.notes
    if request.status is not None:
        session.status = request.status

    await db.commit()

    return {"id": session.id, "updated": True}


@router.delete("/{campaign_id}/sessions/{session_id}")
async def delete_session(
    db: DbSession,
    campaign_id: int,
    session_id: int,
) -> dict:
    """Delete a session."""
    query = select(Session).where(
        Session.id == session_id,
        Session.campaign_id == campaign_id,
    )
    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.delete(session)
    await db.commit()

    return {"deleted": True}


class SessionPrepRequest(BaseModel):
    """Request for session prep generation."""
    provider: str | None = Field(None, description="AI provider: openai, anthropic")
    model: str | None = Field(None, description="Specific model to use")


@router.post("/{campaign_id}/sessions/{session_id}/prep")
async def generate_session_prep_materials(
    db: DbSession,
    campaign_id: int,
    session_id: int,
    request: SessionPrepRequest,
) -> dict:
    """Generate session prep materials using AI."""
    from grimoire.services.session_prep import generate_session_prep
    
    # Get campaign with products
    campaign_query = select(Campaign).where(Campaign.id == campaign_id).options(
        selectinload(Campaign.products),
    )
    campaign_result = await db.execute(campaign_query)
    campaign = campaign_result.scalar_one_or_none()
    
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    # Get session
    session_query = select(Session).where(
        Session.id == session_id,
        Session.campaign_id == campaign_id,
    )
    session_result = await db.execute(session_query)
    session = session_result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Build product list
    products = [
        {
            "id": p.id,
            "title": p.title or p.file_name,
            "file_name": p.file_name,
            "game_system": p.game_system,
            "product_type": p.product_type,
        }
        for p in campaign.products
    ]
    
    try:
        prep = await generate_session_prep(
            campaign_name=campaign.name,
            game_system=campaign.game_system,
            session_number=session.session_number,
            session_title=session.title,
            session_notes=session.notes,
            products=products,
            provider=request.provider,
            model=request.model,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate prep: {e}")
    
    return {
        "campaign_id": campaign_id,
        "session_id": session_id,
        "session_number": session.session_number,
        "prep": prep,
    }
