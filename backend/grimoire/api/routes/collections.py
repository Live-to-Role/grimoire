"""Collection API endpoints."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from grimoire.api.deps import DbSession
from grimoire.models import Collection, CollectionProduct, Product, ProductTag
from grimoire.schemas.collection import (
    CollectionCreate,
    CollectionProductAdd,
    CollectionResponse,
    CollectionUpdate,
    CollectionWithProducts,
)

router = APIRouter()


@router.get("", response_model=list[CollectionResponse])
async def list_collections(db: DbSession) -> list[CollectionResponse]:
    """List all collections."""
    query = select(Collection).order_by(Collection.sort_order, Collection.name)
    result = await db.execute(query)
    collections = result.scalars().all()

    responses = []
    for collection in collections:
        count_query = select(func.count()).where(
            CollectionProduct.collection_id == collection.id
        )
        count_result = await db.execute(count_query)
        product_count = count_result.scalar() or 0

        responses.append(
            CollectionResponse(
                id=collection.id,
                name=collection.name,
                description=collection.description,
                color=collection.color,
                icon=collection.icon,
                sort_order=collection.sort_order,
                created_at=collection.created_at,
                updated_at=collection.updated_at,
                product_count=product_count,
            )
        )

    return responses


@router.post("", response_model=CollectionResponse, status_code=201)
async def create_collection(db: DbSession, data: CollectionCreate) -> CollectionResponse:
    """Create a new collection."""
    collection = Collection(
        name=data.name,
        description=data.description,
        color=data.color,
        icon=data.icon,
    )
    db.add(collection)
    await db.commit()
    await db.refresh(collection)

    return CollectionResponse(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        color=collection.color,
        icon=collection.icon,
        sort_order=collection.sort_order,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
        product_count=0,
    )


@router.get("/{collection_id}", response_model=CollectionWithProducts)
async def get_collection(db: DbSession, collection_id: int) -> CollectionWithProducts:
    """Get a collection with its products."""
    query = select(Collection).where(Collection.id == collection_id)
    result = await db.execute(query)
    collection = result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    products_query = (
        select(Product)
        .join(CollectionProduct)
        .where(CollectionProduct.collection_id == collection_id)
        .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
        .order_by(CollectionProduct.sort_order)
    )
    products_result = await db.execute(products_query)
    products = products_result.scalars().all()

    from grimoire.api.routes.products import product_to_response

    return CollectionWithProducts(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        color=collection.color,
        icon=collection.icon,
        sort_order=collection.sort_order,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
        product_count=len(products),
        products=[product_to_response(p) for p in products],
    )


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    db: DbSession, collection_id: int, data: CollectionUpdate
) -> CollectionResponse:
    """Update a collection."""
    query = select(Collection).where(Collection.id == collection_id)
    result = await db.execute(query)
    collection = result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    update_dict = data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(collection, field, value)

    collection.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(collection)

    count_query = select(func.count()).where(CollectionProduct.collection_id == collection_id)
    count_result = await db.execute(count_query)
    product_count = count_result.scalar() or 0

    return CollectionResponse(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        color=collection.color,
        icon=collection.icon,
        sort_order=collection.sort_order,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
        product_count=product_count,
    )


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(db: DbSession, collection_id: int) -> Response:
    """Delete a collection."""
    query = select(Collection).where(Collection.id == collection_id)
    result = await db.execute(query)
    collection = result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    await db.delete(collection)
    await db.commit()

    return Response(status_code=204)


@router.post("/{collection_id}/products", status_code=201)
async def add_product_to_collection(
    db: DbSession, collection_id: int, data: CollectionProductAdd
) -> dict:
    """Add a product to a collection."""
    collection_query = select(Collection).where(Collection.id == collection_id)
    collection_result = await db.execute(collection_query)
    collection = collection_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    product_query = select(Product).where(Product.id == data.product_id)
    product_result = await db.execute(product_query)
    product = product_result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    existing = await db.execute(
        select(CollectionProduct).where(
            CollectionProduct.collection_id == collection_id,
            CollectionProduct.product_id == data.product_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Product already in collection")

    collection_product = CollectionProduct(
        collection_id=collection_id,
        product_id=data.product_id,
    )
    db.add(collection_product)
    await db.commit()

    return {"message": "Product added to collection"}


@router.delete("/{collection_id}/products/{product_id}", status_code=204)
async def remove_product_from_collection(
    db: DbSession, collection_id: int, product_id: int
) -> Response:
    """Remove a product from a collection."""
    query = select(CollectionProduct).where(
        CollectionProduct.collection_id == collection_id,
        CollectionProduct.product_id == product_id,
    )
    result = await db.execute(query)
    collection_product = result.scalar_one_or_none()

    if not collection_product:
        raise HTTPException(status_code=404, detail="Product not in collection")

    await db.delete(collection_product)
    await db.commit()

    return Response(status_code=204)
