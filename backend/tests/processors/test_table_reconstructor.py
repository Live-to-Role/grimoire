"""Row-major table reconstruction."""

import fitz

from grimoire.processors.table_reconstructor import (
    TableRegion,
    reconstruct_tables,
    rows_to_markdown,
)


def test_rows_to_markdown_emits_header_separator_and_pads():
    md = rows_to_markdown([["Skill", "L1", "L2"], ["Acrobatics*", "+1"]])
    assert md.splitlines() == [
        "| Skill | L1 | L2 |",
        "| --- | --- | --- |",
        "| Acrobatics* | +1 |  |",
    ]


def test_rows_to_markdown_escapes_pipes():
    md = rows_to_markdown([["a|b", "c", "d"]])
    assert "a\\|b" in md


def test_rows_to_markdown_empty():
    assert rows_to_markdown([]) == ""


def test_table_region_markdown_uses_rows():
    region = TableRegion(bbox=(0, 0, 1, 1), rows=[["a", "b", "c"]])
    assert region.markdown.startswith("| a | b | c |")


def test_block_rows_reconstruct_row_major(block_table_pdf):
    doc = fitz.open(str(block_table_pdf))
    try:
        tables = reconstruct_tables(doc[0])
    finally:
        doc.close()

    assert len(tables) == 1
    rows = tables[0].rows
    assert rows[0] == ["Skill", "L1", "L2", "L3", "L4"]
    assert ["Acrobatics*", "+1", "+3", "+5", "+7"] in rows
    # The spanning title must NOT be shredded into the grid
    assert not any("Ta" == cell for row in rows for cell in row)
    assert not any(cell.startswith("Table 1-20") for row in rows for cell in row)


def test_reconstructed_markdown_is_clean(block_table_pdf):
    doc = fitz.open(str(block_table_pdf))
    try:
        md = reconstruct_tables(doc[0])[0].markdown
    finally:
        doc.close()
    assert "| Acrobatics* | +1 | +3 | +5 | +7 |" in md
    assert "| --- |" in md


def test_prose_page_yields_no_tables(text_pdf):
    doc = fitz.open(str(text_pdf))
    try:
        assert reconstruct_tables(doc[0]) == []
    finally:
        doc.close()


def test_bbox_covers_all_rows(block_table_pdf):
    doc = fitz.open(str(block_table_pdf))
    try:
        table = reconstruct_tables(doc[0])[0]
    finally:
        doc.close()
    x0, y0, x1, y1 = table.bbox
    assert x0 < x1 and y0 < y1
    assert y0 >= 100  # below the title line at y=72


def test_word_gap_fallback_recovers_spaced_table(spaced_table_pdf):
    doc = fitz.open(str(spaced_table_pdf))
    try:
        tables = reconstruct_tables(doc[0])
    finally:
        doc.close()

    assert len(tables) == 1
    assert tables[0].rows[0] == ["Skill", "L1", "L2", "L3"]
    assert ["Acrobatics*", "+1", "+3", "+5"] in tables[0].rows


def test_block_path_wins_when_it_finds_a_table(block_table_pdf, monkeypatch):
    """The word fallback must not run when block grouping already succeeded."""
    from grimoire.processors import table_reconstructor

    called = []
    monkeypatch.setattr(
        table_reconstructor,
        "_tables_from_words",
        lambda page: called.append(1) or [],
    )
    doc = fitz.open(str(block_table_pdf))
    try:
        tables = table_reconstructor.reconstruct_tables(doc[0])
    finally:
        doc.close()
    assert tables
    assert called == []
