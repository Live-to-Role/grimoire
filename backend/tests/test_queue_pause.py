"""Tests for queue pause/resume."""
import pytest
from grimoire.services.queue_processor import pause_queue, resume_queue, is_queue_paused


@pytest.mark.asyncio
async def test_pause_and_resume():
    """Queue should toggle between paused and unpaused states."""
    # Starts unpaused
    assert not is_queue_paused()

    pause_queue()
    assert is_queue_paused()

    resume_queue()
    assert not is_queue_paused()


@pytest.mark.asyncio
async def test_resume_when_not_paused_is_noop():
    """Resuming when not paused should not error."""
    resume_queue()
    assert not is_queue_paused()
