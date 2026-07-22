"""Row-major table reconstruction for PDF pages.

pymupdf4llm's table detector shreds dense RPG stat tables: spanning titles get
chopped into cells ("Ta | ble 1 | -20: The half-el | f") and data columns drift
out of alignment. The underlying page data is clean — PyMuPDF reports each table
row as one text block whose lines are that row's cells — so rebuilding row-major
from blocks recovers the true table.

`pymupdf4llm.to_markdown` silently ignores `table_strategy`, so its detector
cannot be switched off; the integration substitutes our output over its table
runs instead (see `substitute_tables`).
"""

from dataclasses import dataclass

# A row must split into at least this many cells to look like tabular data.
MIN_CELLS_PER_ROW = 3
# Cells are short by nature; a long cell means we are looking at prose.
MAX_CELL_CHARS = 30
# Vertical distance (points) between consecutive row blocks still in one table.
MAX_ROW_GAP = 14.0
# A single row is not a table.
MIN_ROWS_PER_TABLE = 2
# Words within this vertical distance (points) belong to the same visual line.
Y_TOLERANCE = 3.0
# Horizontal whitespace (points) that separates two columns.
COLUMN_GAP = 12.0


@dataclass
class TableRegion:
    """A reconstructed table: where it sits on the page, and its rows."""

    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    rows: list[list[str]]

    @property
    def markdown(self) -> str:
        return rows_to_markdown(self.rows)


def rows_to_markdown(rows: list[list[str]]) -> str:
    """Render rows as a markdown pipe table, padding short rows."""
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]

    def render(row: list[str]) -> str:
        return "| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |"

    lines = [render(padded[0]), "|" + "|".join([" --- "] * width) + "|"]
    lines.extend(render(row) for row in padded[1:])
    return "\n".join(lines)


def _cells_from_block_text(text: str) -> list[str] | None:
    """Split one block's text into cells, or None if it isn't a table row."""
    cells = [c.strip() for c in text.split("\n") if c.strip()]
    if len(cells) < MIN_CELLS_PER_ROW:
        return None
    if any(len(c) > MAX_CELL_CHARS for c in cells):
        return None
    return cells


def _group_runs(candidates: list[tuple]) -> list[TableRegion]:
    """Group vertically adjacent row candidates into tables.

    Each candidate is (x0, y0, x1, y1, cells), pre-sorted top-to-bottom.
    """
    tables: list[TableRegion] = []
    run: list[tuple] = []
    for candidate in candidates:
        if run and candidate[1] - run[-1][3] > MAX_ROW_GAP:
            table = _finish_run(run)
            if table is not None:
                tables.append(table)
            run = []
        run.append(candidate)
    table = _finish_run(run)
    if table is not None:
        tables.append(table)
    return tables


def _finish_run(run: list[tuple]) -> TableRegion | None:
    if len(run) < MIN_ROWS_PER_TABLE:
        return None
    return TableRegion(
        bbox=(
            min(c[0] for c in run),
            min(c[1] for c in run),
            max(c[2] for c in run),
            max(c[3] for c in run),
        ),
        rows=[c[4] for c in run],
    )


def _tables_from_blocks(page) -> list[TableRegion]:
    """Primary path: one block per row, its lines are the cells."""
    candidates = []
    for block in page.get_text("blocks"):
        if len(block) >= 7 and block[6] != 0:
            continue  # image block
        cells = _cells_from_block_text(block[4])
        if cells:
            candidates.append((block[0], block[1], block[2], block[3], cells))
    candidates.sort(key=lambda c: (c[1], c[0]))
    return _group_runs(candidates)


def _lines_from_words(words: list[tuple]) -> list[list[tuple]]:
    """Group words into visual lines by vertical proximity."""
    lines: list[list[tuple]] = []
    for word in sorted(words, key=lambda w: (round(w[1], 1), w[0])):
        if lines and abs(lines[-1][0][1] - word[1]) <= Y_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def _cells_from_line(line: list[tuple]) -> list[str] | None:
    """Split one visual line into cells at horizontal gaps."""
    line.sort(key=lambda w: w[0])
    cells: list[str] = []
    current = [line[0][4]]
    for previous, word in zip(line, line[1:]):
        if word[0] - previous[2] >= COLUMN_GAP:
            cells.append(" ".join(current))
            current = [word[4]]
        else:
            current.append(word[4])
    cells.append(" ".join(current))

    cells = [c.strip() for c in cells if c.strip()]
    if len(cells) < MIN_CELLS_PER_ROW:
        return None
    if any(len(c) > MAX_CELL_CHARS for c in cells):
        return None
    return cells


def _tables_from_words(page) -> list[TableRegion]:
    """Fallback: cluster words into rows by y-overlap and columns by x-gap.

    This is pdf-to-markdown's CompactLines/column idea, ported. It handles pages
    where a table's rows do not come back as one block per row.
    """
    words = page.get_text("words")
    if not words:
        return []

    candidates = []
    for line in _lines_from_words(list(words)):
        cells = _cells_from_line(line)
        if not cells:
            continue
        candidates.append((
            min(w[0] for w in line),
            min(w[1] for w in line),
            max(w[2] for w in line),
            max(w[3] for w in line),
            cells,
        ))
    candidates.sort(key=lambda c: (c[1], c[0]))
    return _group_runs(candidates)


def reconstruct_tables(page) -> list[TableRegion]:
    """Rebuild the tables on a `fitz.Page`, ordered top-to-bottom.

    Primary path is block-row grouping; the word-gap fallback runs only when
    blocks yielded nothing.
    """
    regions = _tables_from_blocks(page)
    if not regions:
        regions = _tables_from_words(page)
    return regions
