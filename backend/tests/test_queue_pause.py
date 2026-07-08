"""Tests for DB-backed processing-pause ("I'm working" mode)."""
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from grimoire.models import Setting
from grimoire.services.queue_processor import (
    PROCESSING_PAUSED_KEY,
    is_processing_paused,
    set_processing_paused,
)


@pytest.fixture
def session_maker(engine):
    """A session maker bound to the in-memory test engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_defaults_to_paused_when_unset(session_maker):
    # Ensure no flag row exists in the shared session-scoped engine.
    async with session_maker() as s:
        await s.execute(delete(Setting).where(Setting.key == PROCESSING_PAUSED_KEY))
        await s.commit()

    assert await is_processing_paused(session_maker=session_maker) is True


@pytest.mark.asyncio
async def test_set_and_read_roundtrip(session_maker):
    await set_processing_paused(False, session_maker=session_maker)
    assert await is_processing_paused(session_maker=session_maker) is False

    await set_processing_paused(True, session_maker=session_maker)
    assert await is_processing_paused(session_maker=session_maker) is True
