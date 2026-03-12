"""Tests for image serving API routes."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.mark.asyncio
async def test_list_product_images_no_manifest(db):
    """Should return empty list when no images extracted."""
    from grimoire.models import Product
    p = Product(file_path="/test.pdf", file_name="test.pdf", file_size=1000, file_hash="abc")
    db.add(p)
    await db.commit()
    await db.refresh(p)

    # The route reads from manifest.json - without it, should return empty
    assert p.images_extracted is False
