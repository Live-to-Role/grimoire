"""Settings API endpoints."""

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from grimoire.api.deps import DbSession
from grimoire.models import Setting

router = APIRouter()


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
