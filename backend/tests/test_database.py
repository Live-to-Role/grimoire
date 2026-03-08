"""Tests for database session management."""

import pytest
from grimoire.database import get_db


@pytest.mark.asyncio
async def test_get_db_does_not_auto_commit():
    """get_db should not auto-commit — handlers manage their own transactions."""
    import inspect
    source = inspect.getsource(get_db)
    # Should NOT have an unconditional commit in the happy path
    # The session should just be yielded and closed
    assert "await session.commit()" not in source or "# auto-commit" in source, (
        "get_db should not auto-commit; route handlers manage commits explicitly"
    )
