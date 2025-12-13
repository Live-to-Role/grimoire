"""Tag API endpoints."""

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select

from grimoire.api.deps import DbSession
from grimoire.models import ProductTag, Tag
from grimoire.schemas.tag import TagCreate, TagResponse, TagUpdate

router = APIRouter()


@router.get("", response_model=list[TagResponse])
async def list_tags(
    db: DbSession,
    category: str | None = Query(None, description="Filter by category"),
) -> list[TagResponse]:
    """List all tags."""
    query = select(Tag).order_by(Tag.category, Tag.name)

    if category:
        query = query.where(Tag.category == category)

    result = await db.execute(query)
    tags = result.scalars().all()

    responses = []
    for tag in tags:
        count_query = select(func.count()).where(ProductTag.tag_id == tag.id)
        count_result = await db.execute(count_query)
        product_count = count_result.scalar() or 0

        responses.append(
            TagResponse(
                id=tag.id,
                name=tag.name,
                category=tag.category,
                color=tag.color,
                created_at=tag.created_at,
                product_count=product_count,
            )
        )

    return responses


@router.post("", response_model=TagResponse, status_code=201)
async def create_tag(db: DbSession, data: TagCreate) -> TagResponse:
    """Create a new tag."""
    existing = await db.execute(select(Tag).where(Tag.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tag with this name already exists")

    tag = Tag(
        name=data.name,
        category=data.category,
        color=data.color,
    )
    db.add(tag)
    await db.commit()
    await db.refresh(tag)

    return TagResponse(
        id=tag.id,
        name=tag.name,
        category=tag.category,
        color=tag.color,
        created_at=tag.created_at,
        product_count=0,
    )


@router.get("/{tag_id}", response_model=TagResponse)
async def get_tag(db: DbSession, tag_id: int) -> TagResponse:
    """Get a single tag."""
    query = select(Tag).where(Tag.id == tag_id)
    result = await db.execute(query)
    tag = result.scalar_one_or_none()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    count_query = select(func.count()).where(ProductTag.tag_id == tag.id)
    count_result = await db.execute(count_query)
    product_count = count_result.scalar() or 0

    return TagResponse(
        id=tag.id,
        name=tag.name,
        category=tag.category,
        color=tag.color,
        created_at=tag.created_at,
        product_count=product_count,
    )


@router.patch("/{tag_id}", response_model=TagResponse)
async def update_tag(db: DbSession, tag_id: int, data: TagUpdate) -> TagResponse:
    """Update a tag."""
    query = select(Tag).where(Tag.id == tag_id)
    result = await db.execute(query)
    tag = result.scalar_one_or_none()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    update_dict = data.model_dump(exclude_unset=True)

    if "name" in update_dict and update_dict["name"] != tag.name:
        existing = await db.execute(select(Tag).where(Tag.name == update_dict["name"]))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Tag with this name already exists")

    for field, value in update_dict.items():
        setattr(tag, field, value)

    await db.commit()
    await db.refresh(tag)

    count_query = select(func.count()).where(ProductTag.tag_id == tag.id)
    count_result = await db.execute(count_query)
    product_count = count_result.scalar() or 0

    return TagResponse(
        id=tag.id,
        name=tag.name,
        category=tag.category,
        color=tag.color,
        created_at=tag.created_at,
        product_count=product_count,
    )


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(db: DbSession, tag_id: int) -> Response:
    """Delete a tag."""
    query = select(Tag).where(Tag.id == tag_id)
    result = await db.execute(query)
    tag = result.scalar_one_or_none()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    await db.delete(tag)
    await db.commit()

    return Response(status_code=204)
