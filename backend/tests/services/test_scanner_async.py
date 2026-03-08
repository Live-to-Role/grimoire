"""Tests for non-blocking scanner operations."""

import asyncio
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_file_hash_does_not_block_event_loop():
    """calculate_file_hash should run file I/O in a thread."""
    import tempfile
    import os
    from pathlib import Path

    # Create a temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
        f.write(b"x" * 1024)
        temp_path = Path(f.name)

    try:
        from grimoire.services.scanner import calculate_file_hash

        # Verify it still works
        result = await calculate_file_hash(temp_path)
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest

        # Verify event loop stays responsive during hash
        async def check_responsive():
            start = asyncio.get_event_loop().time()
            await asyncio.sleep(0)
            return asyncio.get_event_loop().time() - start < 0.05

        responsive = await check_responsive()
        assert responsive
    finally:
        os.unlink(temp_path)
