"""Tests for settings caching in queue processor."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_get_setting_caches_result():
    """Repeated calls to get_setting should not hit the database each time."""
    from grimoire.services.queue_processor import get_setting, _settings_cache

    db = AsyncMock()

    # First call should query DB
    mock_setting = MagicMock()
    mock_setting.value = '"test_value"'
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_setting
    db.execute = AsyncMock(return_value=mock_result)

    # Clear cache before test
    _settings_cache.clear()

    result1 = await get_setting(db, "test_key")
    assert result1 == "test_value"
    assert db.execute.call_count == 1

    # Second call should use cache
    result2 = await get_setting(db, "test_key")
    assert result2 == "test_value"
    assert db.execute.call_count == 1  # no additional DB call
