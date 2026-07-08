"""OCR handler flags permanent no-text; transient tooling gaps do not flag."""
import pytest
from unittest.mock import patch
from grimoire.models.product import Product
from grimoire.services.queue_processor import handle_ocr_text_task, TaskError


@pytest.mark.asyncio
async def test_ocr_empty_flags_unextractable(db, tmp_path):
    pdf = tmp_path / "img.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    product = Product(file_path=str(pdf), file_name="img.pdf", file_size=1, file_hash="oc1")
    db.add(product)
    await db.commit()

    with patch("grimoire.services.queue_processor.extract_with_ocr", return_value="   "), \
         patch("grimoire.services.queue_processor.TESSERACT_AVAILABLE", True):
        with pytest.raises(TaskError):
            await handle_ocr_text_task(db, product)

    await db.refresh(product)
    assert product.text_unextractable is True
    assert product.extraction_error


@pytest.mark.asyncio
async def test_ocr_unavailable_does_not_flag(db, tmp_path):
    pdf = tmp_path / "img2.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    product = Product(file_path=str(pdf), file_name="img2.pdf", file_size=1, file_hash="oc2")
    db.add(product)
    await db.commit()

    with patch("grimoire.services.queue_processor.TESSERACT_AVAILABLE", False):
        result = await handle_ocr_text_task(db, product)

    assert result is False
    await db.refresh(product)
    assert not product.text_unextractable
