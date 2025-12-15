"""Settings API endpoints."""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from grimoire.api.deps import DbSession
from grimoire.config import settings as app_settings
from grimoire.models import Setting
from grimoire.services.codex import get_codex_client

router = APIRouter()


class CodexStatusResponse(BaseModel):
    """Codex connection status."""
    available: bool
    mock_mode: bool
    base_url: str
    contribute_enabled: bool
    has_api_key: bool


@router.get("")
async def get_settings(db: DbSession) -> dict:
    """Get all settings."""
    query = select(Setting)
    result = await db.execute(query)
    settings = result.scalars().all()

    return {s.key: json.loads(s.value) for s in settings}


@router.patch("")
async def update_settings(db: DbSession, updates: dict) -> dict:
    """Update settings."""
    for key, value in updates.items():
        query = select(Setting).where(Setting.key == key)
        result = await db.execute(query)
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = json.dumps(value)
        else:
            setting = Setting(key=key, value=json.dumps(value))
            db.add(setting)

    await db.commit()

    return await get_settings(db)


@router.put("")
async def replace_settings(db: DbSession, settings_data: dict) -> dict:
    """Replace all settings with new values."""
    for key, value in settings_data.items():
        if value is None:
            continue
        query = select(Setting).where(Setting.key == key)
        result = await db.execute(query)
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = json.dumps(value)
        else:
            setting = Setting(key=key, value=json.dumps(value))
            db.add(setting)

    await db.commit()

    return await get_settings(db)


@router.get("/{key}")
async def get_setting(db: DbSession, key: str) -> dict:
    """Get a single setting."""
    query = select(Setting).where(Setting.key == key)
    result = await db.execute(query)
    setting = result.scalar_one_or_none()

    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")

    return {key: json.loads(setting.value)}


@router.put("/{key}")
async def set_setting(db: DbSession, key: str, value: dict) -> dict:
    """Set a single setting."""
    query = select(Setting).where(Setting.key == key)
    result = await db.execute(query)
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = json.dumps(value.get("value", value))
    else:
        setting = Setting(key=key, value=json.dumps(value.get("value", value)))
        db.add(setting)

    await db.commit()

    return {key: json.loads(setting.value)}


@router.delete("/{key}", status_code=204)
async def delete_setting(db: DbSession, key: str) -> None:
    """Delete a setting."""
    query = select(Setting).where(Setting.key == key)
    result = await db.execute(query)
    setting = result.scalar_one_or_none()

    if setting:
        await db.delete(setting)
        await db.commit()


@router.get("/codex/status", response_model=CodexStatusResponse)
async def get_codex_status() -> CodexStatusResponse:
    """Get Codex API connection status."""
    client = get_codex_client()
    available = await client.is_available()
    
    return CodexStatusResponse(
        available=available,
        mock_mode=client.use_mock,
        base_url=app_settings.codex_api_url,
        contribute_enabled=app_settings.codex_contribute_enabled,
        has_api_key=bool(app_settings.codex_api_key),
    )


class SyncRequest(BaseModel):
    """Request for syncing with Codex."""
    overwrite_existing: bool = False
    only_unidentified: bool = True


@router.post("/codex/sync")
async def sync_with_codex(db: DbSession, request: SyncRequest) -> dict:
    """Sync all products with Codex metadata."""
    from grimoire.services.sync_service import sync_all_products
    
    return await sync_all_products(
        db=db,
        overwrite_existing=request.overwrite_existing,
        only_unidentified=request.only_unidentified,
    )


@router.post("/codex/sync/{product_id}")
async def sync_product_with_codex(
    db: DbSession,
    product_id: int,
    overwrite: bool = False,
) -> dict:
    """Sync a single product with Codex metadata."""
    from grimoire.services.sync_service import sync_product_from_codex
    
    from grimoire.models import Product
    
    product_query = select(Product).where(Product.id == product_id)
    result = await db.execute(product_query)
    product = result.scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    return await sync_product_from_codex(
        db=db,
        product=product,
        overwrite_existing=overwrite,
    )


@router.get("/codex/sync-status")
async def get_codex_sync_status(db: DbSession) -> dict:
    """Get sync status including pending contributions."""
    from grimoire.services.sync_service import get_sync_status
    return await get_sync_status(db)


@router.post("/codex/sync-contributions")
async def sync_pending_to_codex(db: DbSession) -> dict:
    """Sync all pending local edits to Codex."""
    from grimoire.services.sync_service import sync_pending_contributions
    return await sync_pending_contributions(db)
