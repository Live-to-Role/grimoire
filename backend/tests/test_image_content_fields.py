"""Tests for image content fields on Product model."""
import pytest
from grimoire.models import Product


def test_product_has_image_content_fields():
    """Product model should have is_image_content, images_extracted, image_count."""
    p = Product(
        file_path="/test.pdf",
        file_name="test.pdf",
        file_size=1000,
        file_hash="abc123",
    )
    assert not p.is_image_content
    assert not p.images_extracted
    assert p.image_count is None
