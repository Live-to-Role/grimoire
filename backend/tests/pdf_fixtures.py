"""Generated-PDF fixtures for document processing tests."""

import fitz
import pytest
from PIL import Image


@pytest.fixture
def text_pdf(tmp_path):
    """A one-page text-based PDF (US Letter)."""
    pdf_path = tmp_path / "text.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Grimoire Test Document", fontsize=24)
    page.insert_text(
        (72, 144),
        "Some body text for extraction verification purposes.",
        fontsize=12,
    )
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def scanned_pdf(tmp_path):
    """A one-page image-only PDF (no text layer) — simulates a scan.

    The image is rendered from a text page so OCR tests have real
    glyphs to recognize.
    """
    # Render a text page to an image
    src = fitz.open()
    src_page = src.new_page(width=612, height=792)
    src_page.insert_text((72, 200), "GRIMOIRE OCR SAMPLE", fontsize=36)
    pix = src_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    img_path = tmp_path / "page.png"
    pix.save(str(img_path))
    src.close()

    # Build a PDF whose only content is that image
    pdf_path = tmp_path / "scanned.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(page.rect, filename=str(img_path))
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def art_front_matter_pdf(tmp_path):
    """The corebook shape: 3 art-only front-matter pages, then 7 text body pages.

    This is the document the old first-3-pages sampler misrouted to OCR.
    """
    img = Image.new("RGB", (600, 780), (30, 30, 60))
    img_path = tmp_path / "cover.png"
    img.save(img_path)

    pdf_path = tmp_path / "corebook.pdf"
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, filename=str(img_path))
        # Front matter carries a trace of text (a credit line), well under MIN_CHARS
        page.insert_text((72, 700), f"vol {i}", fontsize=9)
    for _ in range(7):
        page = doc.new_page(width=612, height=792)
        body = "The adventurer descends into the vault beneath the ruined keep. " * 6
        page.insert_textbox(fitz.Rect(60, 60, 550, 730), body, fontsize=11)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def block_table_pdf(tmp_path):
    """A page whose table rows are each one text block with newline-separated cells.

    This is the shape PyMuPDF reports for the real "Table 1-20: The Half-Elf"
    stat table, where pymupdf4llm's detector shreds the spanning title into
    'Ta | ble 1 | -20: The half-el | f'.
    """
    pdf_path = tmp_path / "block_table.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    page.insert_text((72, 72), "Table 1-20: The Half-Elf", fontsize=14)

    rows = [
        ["Skill", "L1", "L2", "L3", "L4"],
        ["Acrobatics*", "+1", "+3", "+5", "+7"],
        ["Bluff", "+0", "+2", "+4", "+6"],
        ["Stealth", "+2", "+4", "+6", "+8"],
    ]
    # Cells spread across the row with wide column gaps: MuPDF then reports each
    # row as one block whose cells are separate lines, which is the real corebook
    # shape. Rows 20pt apart stay within MAX_ROW_GAP of each other.
    xs = [72, 220, 320, 420, 500]
    y = 120
    for row in rows:
        for x, cell in zip(xs, row):
            page.insert_text((x, y), cell, fontsize=10)
        y += 20

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def repeated_image_pdf(tmp_path):
    """A three-page PDF with the identical image on every page."""
    img = Image.new("RGB", (400, 400), (180, 40, 40))
    img_path = tmp_path / "art.png"
    img.save(img_path)

    pdf_path = tmp_path / "repeated.pdf"
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page(width=612, height=792)
        page.insert_image(fitz.Rect(100, 100, 500, 500), filename=str(img_path))
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path
