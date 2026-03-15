# Revision Handling Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect product revisions by filename stem matching, surface candidates in the duplicates view, and supersede older versions with metadata transfer.

**Architecture:** Extend the existing duplicate system with stem normalization for revision detection. New `is_superseded`/`superseded_by_id` columns on Product. Revision candidates appear in the duplicates view under a "Revisions" filter with confirm/dismiss actions.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, SQLite/aiosqlite, React 18, TypeScript, React Query v5

**Spec:** `docs/superpowers/specs/2026-03-15-revision-handling-design.md`

---

## Chunk 1: Core Engine & Data Model

### Task 1: Stem Normalization Function

**Files:**
- Create: `backend/grimoire/services/revision_service.py`
- Create: `backend/tests/services/test_revision_service.py`

- [ ] **Step 1: Write failing tests for stem normalization**

```python
# backend/tests/services/test_revision_service.py
import pytest
from grimoire.services.revision_service import normalize_stem, has_revision_indicator


class TestNormalizeStem:
    def test_basic_filename(self):
        assert normalize_stem("A_Conspiracy_of_Ravens.pdf") == "a_conspiracy_of_ravens"

    def test_strips_pdf_suffix(self):
        assert normalize_stem("A_Conspiracy_of_Ravens-PDF.pdf") == "a_conspiracy_of_ravens"
        assert normalize_stem("A_Conspiracy_of_Ravens_PDF.pdf") == "a_conspiracy_of_ravens"

    def test_strips_revised_suffix(self):
        assert normalize_stem("A_Conspiracy_of_Ravens-PDF_(Revised).pdf") == "a_conspiracy_of_ravens"
        assert normalize_stem("A_Conspiracy_of_Ravens_Revised.pdf") == "a_conspiracy_of_ravens"

    def test_strips_version_suffix(self):
        assert normalize_stem("Monster_Manual_v2.pdf") == "monster_manual"
        assert normalize_stem("Monster_Manual_v1.2.pdf") == "monster_manual"

    def test_strips_edition_suffix(self):
        assert normalize_stem("Players_Handbook_2nd_Edition.pdf") == "players_handbook"

    def test_strips_updated_errata_final(self):
        assert normalize_stem("Core_Rules_Updated.pdf") == "core_rules"
        assert normalize_stem("Core_Rules_Errata.pdf") == "core_rules"
        assert normalize_stem("Core_Rules_Final.pdf") == "core_rules"

    def test_strips_print_friendly(self):
        assert normalize_stem("Dungeon_Map_(Print_Friendly).pdf") == "dungeon_map"
        assert normalize_stem("Dungeon_Map_(Print Friendly).pdf") == "dungeon_map"

    def test_no_false_positive_mid_word(self):
        """Patterns only match at trailing position, not mid-filename."""
        assert normalize_stem("The_Final_Dungeon.pdf") == "the_final_dungeon"
        assert normalize_stem("The_PDF_Guide_to_Dragons.pdf") == "the_pdf_guide_to_dragons"

    def test_collapses_separators(self):
        assert normalize_stem("Tomb - of - Horrors.pdf") == "tomb_of_horrors"
        assert normalize_stem("Tomb__of__Horrors.pdf") == "tomb_of_horrors"

    def test_case_insensitive(self):
        assert normalize_stem("MONSTER_MANUAL-pdf.pdf") == "monster_manual"
        assert normalize_stem("Monster_Manual-PDF_(REVISED).pdf") == "monster_manual"

    def test_multiple_suffixes_stripped(self):
        """Format tag + revision pattern both stripped."""
        assert normalize_stem("Adventure_PDF_Revised.pdf") == "adventure"
        assert normalize_stem("Adventure-PDF_(Revised).pdf") == "adventure"

    def test_empty_after_strip(self):
        """Edge case: if stripping leaves nothing, return what we can."""
        assert normalize_stem("PDF.pdf") == "pdf"


class TestHasRevisionIndicator:
    def test_revised(self):
        assert has_revision_indicator("A_Conspiracy_of_Ravens-PDF_(Revised).pdf") is True

    def test_version(self):
        assert has_revision_indicator("Monster_Manual_v2.pdf") is True

    def test_no_indicator(self):
        assert has_revision_indicator("A_Conspiracy_of_Ravens-PDF.pdf") is False

    def test_final(self):
        assert has_revision_indicator("Core_Rules_Final.pdf") is True

    def test_mid_word_not_indicator(self):
        assert has_revision_indicator("The_Final_Dungeon.pdf") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_stem'`

- [ ] **Step 3: Implement stem normalization**

```python
# backend/grimoire/services/revision_service.py
"""Revision detection service — identifies products that are revisions of each other."""

import re
from pathlib import Path

# Trailing format tags to strip (case-insensitive)
FORMAT_TAGS = [
    r"[-_]PDF",
]

# Trailing revision patterns to strip (case-insensitive)
# Order matters: longer/more specific patterns first
REVISION_PATTERNS = [
    r"\(Print[_ ]Friendly\)",
    r"[-_]2nd[_ ]Edition",
    r"[-_]3rd[_ ]Edition",
    r"[-_]Revised",
    r"\(Revised\)",
    r"[-_]Updated",
    r"\(Updated\)",
    r"[-_]Errata",
    r"\(Errata\)",
    r"[-_]Final",
    r"\(Final\)",
    r"[-_]v\d+(?:\.\d+)?",  # _v2, _v1.2
]

# Combined pattern for detecting if a filename has any revision indicator (trailing only)
_REVISION_DETECT_RE = re.compile(
    r"(?:" + "|".join(REVISION_PATTERNS) + r")\s*$",
    re.IGNORECASE,
)

# Build a single regex that strips trailing format tags and revision patterns
# Apply iteratively since a filename may have both (e.g., "Adventure-PDF_(Revised)")
_FORMAT_TAG_RE = re.compile(
    r"(?:" + "|".join(FORMAT_TAGS) + r")\s*$",
    re.IGNORECASE,
)
_REVISION_PATTERN_RE = re.compile(
    r"(?:" + "|".join(REVISION_PATTERNS) + r")\s*$",
    re.IGNORECASE,
)
_SEPARATOR_RE = re.compile(r"[-_ ]+")


def normalize_stem(filename: str) -> str:
    """Normalize a filename to a canonical stem for revision matching.

    Steps:
    1. Remove file extension
    2. Strip trailing format tags (-PDF, _PDF)
    3. Strip trailing revision patterns (_Revised, _v2, etc.)
    4. Lowercase, collapse separators, strip trailing separators
    """
    stem = Path(filename).stem

    # Iteratively strip format tags and revision patterns from the end
    # Loop because stripping one may reveal another (e.g., "Foo-PDF_(Revised)")
    changed = True
    while changed:
        changed = False
        new_stem = _FORMAT_TAG_RE.sub("", stem)
        if new_stem != stem:
            stem = new_stem
            changed = True
        new_stem = _REVISION_PATTERN_RE.sub("", stem)
        if new_stem != stem:
            stem = new_stem
            changed = True

    # Lowercase, collapse separators
    stem = stem.lower()
    stem = _SEPARATOR_RE.sub("_", stem)
    stem = stem.strip("_")

    return stem


def has_revision_indicator(filename: str) -> bool:
    """Check if a filename contains a trailing revision indicator."""
    stem = Path(filename).stem
    # Strip format tags first so "Foo-PDF_(Revised)" works
    stem = _FORMAT_TAG_RE.sub("", stem)
    return bool(_REVISION_DETECT_RE.search(stem))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/revision_service.py backend/tests/services/test_revision_service.py
git commit -m "feat(revision): add stem normalization and revision indicator detection"
```

---

### Task 2: Product Model Changes

**Files:**
- Modify: `backend/grimoire/models/product.py` (add columns ~line 119, relationship ~line 152, indexes ~line 29)
- Modify: `backend/grimoire/database.py` (add to `_ensure_columns()` ~line 146)
- Create: `backend/tests/services/test_revision_model.py`

- [ ] **Step 1: Write failing test for new model fields**

```python
# backend/tests/services/test_revision_model.py
import pytest
from sqlalchemy import select
from grimoire.models.product import Product


@pytest.mark.asyncio
async def test_product_has_superseded_fields(db):
    """Product model has is_superseded, superseded_by_id, normalized_stem."""
    product = Product(
        file_path="/test/book.pdf",
        file_name="book.pdf",
        title="Book",
        file_hash="abc123",
        file_size=12345,
        normalized_stem="book",
    )
    db.add(product)
    await db.flush()

    result = await db.execute(select(Product).where(Product.id == product.id))
    p = result.scalar_one()
    assert p.normalized_stem == "book"
    assert p.is_superseded is False
    assert p.superseded_by_id is None


@pytest.mark.asyncio
async def test_superseded_by_relationship(db):
    """superseded_by relationship resolves to the newer product."""
    old = Product(file_path="/test/old.pdf", file_name="old.pdf", title="Old", file_hash="aaa", file_size=100)
    new = Product(file_path="/test/new.pdf", file_name="new.pdf", title="New", file_hash="bbb", file_size=200)
    db.add_all([old, new])
    await db.flush()

    old.is_superseded = True
    old.superseded_by_id = new.id
    await db.flush()

    result = await db.execute(select(Product).where(Product.id == old.id))
    p = result.scalar_one()
    assert p.superseded_by_id == new.id
    assert p.is_superseded is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/services/test_revision_model.py -v`
Expected: FAIL — `TypeError` or `AttributeError` for missing columns

- [ ] **Step 3: Add columns and relationship to Product model**

In `backend/grimoire/models/product.py`:

Add to indexes (around line 29-30, alongside existing `ix_products_is_missing`):
```python
Index("ix_products_is_superseded", "is_superseded"),
Index("ix_products_normalized_stem", "normalized_stem"),
```

Add columns after `is_missing` / `missing_since` (around line 121):
```python
# Revision tracking
normalized_stem: Mapped[str | None] = mapped_column(String(500), nullable=True)
is_superseded: Mapped[bool] = mapped_column(Boolean, default=False)
superseded_by_id: Mapped[int | None] = mapped_column(
    Integer, ForeignKey("products.id"), nullable=True
)
```

Update the `duplicate_reason` column comment (around line 113) to include the new value:
```python
duplicate_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 'exact_hash', 'same_content', 'revision'
```

Add relationship after the existing `duplicate_of` relationship (around line 152):
```python
superseded_by: Mapped["Product | None"] = relationship(
    "Product",
    remote_side="Product.id",
    foreign_keys="Product.superseded_by_id",
)
```

- [ ] **Step 4: Add columns to `_ensure_columns()` in database.py**

In `backend/grimoire/database.py`, add to the `migrations` list (around line 146-152):
```python
("products", "normalized_stem", "TEXT"),
("products", "is_superseded", "BOOLEAN DEFAULT 0"),
("products", "superseded_by_id", "INTEGER REFERENCES products(id)"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/services/test_revision_model.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite to verify no regressions**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS (55+ tests)

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/models/product.py backend/grimoire/database.py backend/tests/services/test_revision_model.py
git commit -m "feat(revision): add is_superseded, superseded_by_id, normalized_stem to Product model"
```

---

### Task 3: Normalized Stem Backfill

**Files:**
- Modify: `backend/grimoire/database.py` (add backfill function, call after `_ensure_columns()`)
- Modify: `backend/grimoire/services/revision_service.py` (used by backfill)

- [ ] **Step 1: Write failing test for backfill**

Add to `backend/tests/services/test_revision_model.py`:
```python
from grimoire.database import _backfill_normalized_stems


@pytest.mark.asyncio
async def test_backfill_normalized_stems(db):
    """Backfill computes normalized_stem for products missing it."""
    p1 = Product(
        file_path="/test/Monster_Manual-PDF.pdf",
        file_name="Monster_Manual-PDF.pdf",
        title="Monster Manual",
        file_hash="aaa",
        file_size=12345,
    )
    p2 = Product(
        file_path="/test/Monster_Manual-PDF_(Revised).pdf",
        file_name="Monster_Manual-PDF_(Revised).pdf",
        title="Monster Manual Revised",
        file_hash="bbb",
        file_size=12345,
        normalized_stem="already_set",
    )
    db.add_all([p1, p2])
    await db.commit()

    await _backfill_normalized_stems(db)

    result = await db.execute(select(Product).where(Product.id == p1.id))
    assert result.scalar_one().normalized_stem == "monster_manual"

    # Should not overwrite existing stem
    result = await db.execute(select(Product).where(Product.id == p2.id))
    assert result.scalar_one().normalized_stem == "already_set"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/services/test_revision_model.py::test_backfill_normalized_stems -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement backfill function**

In `backend/grimoire/database.py`, add after the `_ensure_columns()` function:

```python
async def _backfill_normalized_stems(session):
    """One-time backfill: compute normalized_stem for all products missing it."""
    from grimoire.models.product import Product
    from grimoire.services.revision_service import normalize_stem  # import inside function to avoid circular imports
    result = await session.execute(
        select(Product).where(Product.normalized_stem.is_(None))
    )
    products = result.scalars().all()
    for product in products:
        product.normalized_stem = normalize_stem(product.file_name)
    if products:
        await session.commit()
```

Call it in `init_db()` inside a new session block after `_ensure_columns()` (around line 165). Do NOT put it in the `engine.begin()` block — it needs a session, not a raw connection:
```python
async with async_session_maker() as session:
    await _backfill_normalized_stems(session)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/services/test_revision_model.py::test_backfill_normalized_stems -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/database.py backend/tests/services/test_revision_model.py
git commit -m "feat(revision): add normalized_stem backfill on startup"
```

---

## Chunk 2: Revision Detection & Confirmation

### Task 4: Revision Candidate Detection

**Files:**
- Modify: `backend/grimoire/services/revision_service.py`
- Modify: `backend/tests/services/test_revision_service.py`

- [ ] **Step 1: Write failing tests for candidate detection**

Add to `backend/tests/services/test_revision_service.py`:

```python
from grimoire.models.product import Product
from grimoire.services.revision_service import (
    normalize_stem,
    has_revision_indicator,
    find_revision_candidates,
    determine_newer_product,
)


@pytest.mark.asyncio
async def test_find_revision_candidates(db):
    """Products with same normalized_stem but different hash are candidates."""
    old = Product(
        file_path="/test/Ravens-PDF.pdf",
        file_name="Ravens-PDF.pdf",
        title="Ravens",
        file_hash="aaa",
        file_size=100,
        normalized_stem="ravens",
    )
    revised = Product(
        file_path="/test/Ravens-PDF_(Revised).pdf",
        file_name="Ravens-PDF_(Revised).pdf",
        title="Ravens Revised",
        file_hash="bbb",
        file_size=200,
        normalized_stem="ravens",
    )
    unrelated = Product(
        file_path="/test/Dragons.pdf",
        file_name="Dragons.pdf",
        title="Dragons",
        file_hash="ccc",
        file_size=300,
        normalized_stem="dragons",
    )
    db.add_all([old, revised, unrelated])
    await db.commit()

    groups = await find_revision_candidates(db)
    assert len(groups) == 1
    assert groups[0]["normalized_stem"] == "ravens"
    assert len(groups[0]["products"]) == 2


@pytest.mark.asyncio
async def test_find_revision_candidates_excludes_already_marked(db):
    """Already-superseded or already-duplicate products are excluded."""
    old = Product(
        file_path="/test/Ravens.pdf",
        file_name="Ravens.pdf",
        title="Ravens",
        file_hash="aaa",
        file_size=100,
        normalized_stem="ravens",
        is_superseded=True,
    )
    revised = Product(
        file_path="/test/Ravens_Revised.pdf",
        file_name="Ravens_Revised.pdf",
        title="Ravens Revised",
        file_hash="bbb",
        file_size=200,
        normalized_stem="ravens",
    )
    db.add_all([old, revised])
    await db.commit()

    groups = await find_revision_candidates(db)
    assert len(groups) == 0


@pytest.mark.asyncio
async def test_find_revision_candidates_three_way_group(db):
    """Three products with same stem form one group."""
    p1 = Product(file_path="/t/A.pdf", file_name="A.pdf", file_hash="a1", file_size=100, normalized_stem="book", title="A")
    p2 = Product(file_path="/t/A_v2.pdf", file_name="A_v2.pdf", file_hash="a2", file_size=200, normalized_stem="book", title="A v2")
    p3 = Product(file_path="/t/A_Revised.pdf", file_name="A_Revised.pdf", file_hash="a3", file_size=300, normalized_stem="book", title="A Rev")
    db.add_all([p1, p2, p3])
    await db.commit()

    groups = await find_revision_candidates(db)
    assert len(groups) == 1
    assert len(groups[0]["products"]) == 3


class TestDetermineNewerProduct:
    def test_revision_indicator_wins(self):
        """Product with revision indicator is newer."""
        old = Product(file_path="/t/A.pdf", file_name="A.pdf", file_hash="a1", title="A")
        new = Product(file_path="/t/A_Revised.pdf", file_name="A_Revised.pdf", file_hash="a2", title="A Rev")
        assert determine_newer_product([old, new]) == new

    def test_falls_back_to_file_modified(self):
        """When no indicators, use file_modified_at."""
        from datetime import datetime
        old = Product(file_path="/t/A.pdf", file_name="A.pdf", file_hash="a1", title="A")
        old.file_modified_at = datetime(2025, 1, 1)
        new = Product(file_path="/t/B.pdf", file_name="B.pdf", file_hash="b1", title="B")
        new.file_modified_at = datetime(2026, 1, 1)
        assert determine_newer_product([old, new]) == new

    def test_falls_back_to_created_at(self):
        """When no indicators or mtime, use created_at."""
        from datetime import datetime
        old = Product(file_path="/t/A.pdf", file_name="A.pdf", file_hash="a1", title="A")
        old.created_at = datetime(2025, 1, 1)
        new = Product(file_path="/t/B.pdf", file_name="B.pdf", file_hash="b1", title="B")
        new.created_at = datetime(2026, 1, 1)
        assert determine_newer_product([old, new]) == new
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py -v -k "candidate or newer"`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement candidate detection**

Add to `backend/grimoire/services/revision_service.py`:

```python
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from grimoire.models.product import Product


async def find_revision_candidates(db: AsyncSession) -> list[dict]:
    """Find groups of products that share a normalized_stem but have different hashes.

    Returns list of groups: [{"normalized_stem": str, "products": [Product, ...]}]
    Excludes products already marked as duplicates, superseded, or missing.
    """
    # Find stems with >1 non-excluded product
    stem_counts = (
        select(Product.normalized_stem, func.count(Product.id).label("cnt"))
        .where(
            Product.normalized_stem.isnot(None),
            Product.is_duplicate == False,
            Product.is_superseded == False,
            Product.is_missing == False,
        )
        .group_by(Product.normalized_stem)
        .having(func.count(Product.id) > 1)
    )
    result = await db.execute(stem_counts)
    stems = [row.normalized_stem for row in result.all()]

    if not stems:
        return []

    # Fetch products for those stems
    query = (
        select(Product)
        .where(
            Product.normalized_stem.in_(stems),
            Product.is_duplicate == False,
            Product.is_superseded == False,
            Product.is_missing == False,
        )
        .order_by(Product.normalized_stem)
    )
    result = await db.execute(query)
    products = result.scalars().all()

    # Group by stem, only keep groups with >1 distinct hash
    from itertools import groupby
    groups = []
    for stem, group_iter in groupby(products, key=lambda p: p.normalized_stem):
        group_products = list(group_iter)
        hashes = {p.file_hash for p in group_products}
        if len(hashes) > 1:
            groups.append({
                "normalized_stem": stem,
                "products": group_products,
            })

    return groups


def determine_newer_product(products: list[Product]) -> Product:
    """Determine which product in a group is the newest (canonical revision).

    Priority:
    1. Has a revision indicator in filename
    2. Most recent file_modified_at
    3. Most recent created_at
    """
    def sort_key(p: Product) -> tuple:
        has_indicator = has_revision_indicator(p.file_name) if p.file_name else False
        mtime = p.file_modified_at or datetime.min
        ctime = p.created_at or datetime.min
        return (has_indicator, mtime, ctime)

    return max(products, key=sort_key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/revision_service.py backend/tests/services/test_revision_service.py
git commit -m "feat(revision): add revision candidate detection and newer-product determination"
```

---

### Task 5: Mark Revision Candidates

**Files:**
- Modify: `backend/grimoire/services/revision_service.py`
- Modify: `backend/tests/services/test_revision_service.py`

- [ ] **Step 1: Write failing tests for marking candidates**

Add to `backend/tests/services/test_revision_service.py`:

```python
from grimoire.services.revision_service import mark_revision_candidates


@pytest.mark.asyncio
async def test_mark_revision_candidates(db):
    """Marking sets is_duplicate, duplicate_of_id, duplicate_reason on older products."""
    old = Product(
        file_path="/t/Ravens.pdf", file_name="Ravens.pdf", file_hash="aaa",
        file_size=100, normalized_stem="ravens", title="Ravens",
    )
    revised = Product(
        file_path="/t/Ravens_Revised.pdf", file_name="Ravens_Revised.pdf", file_hash="bbb",
        file_size=200, normalized_stem="ravens", title="Ravens Revised",
    )
    db.add_all([old, revised])
    await db.commit()

    count = await mark_revision_candidates(db)
    assert count == 1

    await db.refresh(old)
    assert old.is_duplicate is True
    assert old.duplicate_of_id == revised.id
    assert old.duplicate_reason == "revision"

    await db.refresh(revised)
    assert revised.is_duplicate is False


@pytest.mark.asyncio
async def test_mark_revision_candidates_idempotent(db):
    """Running twice doesn't double-mark."""
    old = Product(
        file_path="/t/Ravens.pdf", file_name="Ravens.pdf", file_hash="aaa",
        file_size=100, normalized_stem="ravens", title="Ravens",
    )
    revised = Product(
        file_path="/t/Ravens_Revised.pdf", file_name="Ravens_Revised.pdf", file_hash="bbb",
        file_size=200, normalized_stem="ravens", title="Ravens Revised",
    )
    db.add_all([old, revised])
    await db.commit()

    count1 = await mark_revision_candidates(db)
    count2 = await mark_revision_candidates(db)
    assert count1 == 1
    assert count2 == 0  # Already marked, excluded from candidates
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py -v -k "mark_revision"`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement marking function**

Add to `backend/grimoire/services/revision_service.py`:

```python
async def mark_revision_candidates(db: AsyncSession) -> int:
    """Find revision candidate groups and mark older products as revision duplicates.

    Returns count of newly marked candidates.
    """
    groups = await find_revision_candidates(db)
    marked = 0

    for group in groups:
        newer = determine_newer_product(group["products"])
        for product in group["products"]:
            if product.id != newer.id:
                product.is_duplicate = True
                product.duplicate_of_id = newer.id
                product.duplicate_reason = "revision"
                marked += 1

    if marked:
        await db.commit()

    return marked
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/revision_service.py backend/tests/services/test_revision_service.py
git commit -m "feat(revision): add mark_revision_candidates to flag older revisions"
```

---

### Task 6: Confirm & Dismiss Revisions (Metadata Transfer + Supersede)

**Files:**
- Modify: `backend/grimoire/services/revision_service.py`
- Modify: `backend/tests/services/test_revision_service.py`

- [ ] **Step 1: Write failing tests for confirm and dismiss**

Add to `backend/tests/services/test_revision_service.py`:

```python
from grimoire.services.revision_service import confirm_revision, dismiss_revision


@pytest.mark.asyncio
async def test_confirm_revision_transfers_metadata(db):
    """Confirming transfers metadata from old to new where new is empty."""
    old = Product(
        file_path="/t/Ravens.pdf", file_name="Ravens.pdf", file_hash="aaa",
        file_size=100, normalized_stem="ravens", title="Ravens",
        author="Author A", publisher="Publisher X", game_system="D&D 5e",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/Ravens_Revised.pdf", file_name="Ravens_Revised.pdf", file_hash="bbb",
        file_size=200, normalized_stem="ravens", title="Ravens Revised",
        author=None, publisher=None, game_system="D&D 5e",  # game_system already set
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    await confirm_revision(db, old.id)

    await db.refresh(old)
    await db.refresh(new)

    # Metadata transferred where new was empty
    assert new.author == "Author A"
    assert new.publisher == "Publisher X"
    # Not overwritten where new had value
    assert new.game_system == "D&D 5e"

    # Old product is superseded
    assert old.is_superseded is True
    assert old.superseded_by_id == new.id


@pytest.mark.asyncio
async def test_confirm_revision_clears_duplicate_flag(db):
    """After confirming, old product's duplicate flags are cleared (superseded takes over)."""
    old = Product(
        file_path="/t/A.pdf", file_name="A.pdf", file_hash="aaa",
        file_size=100, normalized_stem="a", title="A",
        is_duplicate=True, duplicate_of_id=None, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/A_v2.pdf", file_name="A_v2.pdf", file_hash="bbb",
        file_size=200, normalized_stem="a", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    await confirm_revision(db, old.id)

    await db.refresh(old)
    assert old.is_duplicate is False
    assert old.duplicate_of_id is None
    assert old.duplicate_reason is None
    assert old.is_superseded is True


@pytest.mark.asyncio
async def test_dismiss_revision(db):
    """Dismissing clears all duplicate/revision markers."""
    old = Product(
        file_path="/t/A.pdf", file_name="A.pdf", file_hash="aaa",
        file_size=100, normalized_stem="a", title="A",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/A_v2.pdf", file_name="A_v2.pdf", file_hash="bbb",
        file_size=200, normalized_stem="a", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    await dismiss_revision(db, old.id)

    await db.refresh(old)
    assert old.is_duplicate is False
    assert old.duplicate_of_id is None
    assert old.duplicate_reason is None
    assert old.is_superseded is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py -v -k "confirm or dismiss"`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement confirm and dismiss**

Add to `backend/grimoire/services/revision_service.py`:

```python
from sqlalchemy import update as sa_update

# Fields to transfer during revision confirmation
TRANSFERABLE_FIELDS = [
    "title", "author", "publisher", "publication_year", "description",
    "game_system", "genre", "product_type", "setting",
    "series", "series_order",
    "level_range_min", "level_range_max",
    "party_size_min", "party_size_max",
    "estimated_runtime", "format", "isbn", "msrp",
    "dtrpg_url", "itch_url", "themes", "content_warnings",
]

RUN_FIELDS = ["run_status", "run_rating", "run_difficulty", "run_completed_at"]


async def confirm_revision(db: AsyncSession, old_product_id: int) -> dict:
    """Confirm a revision candidate: transfer metadata, supersede the old product.

    Returns dict with transfer summary.
    """
    result = await db.execute(select(Product).where(Product.id == old_product_id))
    old = result.scalar_one_or_none()
    if not old or old.duplicate_reason != "revision" or not old.duplicate_of_id:
        raise ValueError(f"Product {old_product_id} is not a revision candidate")

    result = await db.execute(select(Product).where(Product.id == old.duplicate_of_id))
    new = result.scalar_one_or_none()
    if not new:
        raise ValueError(f"Newer product {old.duplicate_of_id} not found")

    # 1. Selective metadata transfer
    transferred = []
    for field in TRANSFERABLE_FIELDS:
        old_val = getattr(old, field)
        new_val = getattr(new, field)
        if old_val is not None and (new_val is None or new_val == "" or new_val == []):
            setattr(new, field, old_val)
            transferred.append(field)

    # 2. Relationship transfer (tags, collections)
    # Import here to avoid circular imports
    from grimoire.models.tag import ProductTag
    try:
        from grimoire.models.collection import CollectionProduct
        has_collections = True
    except ImportError:
        has_collections = False

    # Transfer tags
    old_tags_result = await db.execute(
        select(ProductTag).where(ProductTag.product_id == old.id)
    )
    for tag_assoc in old_tags_result.scalars().all():
        # Check if new product already has this tag
        existing = await db.execute(
            select(ProductTag).where(
                ProductTag.product_id == new.id,
                ProductTag.tag_id == tag_assoc.tag_id,
            )
        )
        if not existing.scalar_one_or_none():
            db.add(ProductTag(product_id=new.id, tag_id=tag_assoc.tag_id))

    # Transfer collections if model exists
    if has_collections:
        old_colls_result = await db.execute(
            select(CollectionProduct).where(CollectionProduct.product_id == old.id)
        )
        for coll_assoc in old_colls_result.scalars().all():
            existing = await db.execute(
                select(CollectionProduct).where(
                    CollectionProduct.product_id == new.id,
                    CollectionProduct.collection_id == coll_assoc.collection_id,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(CollectionProduct(product_id=new.id, collection_id=coll_assoc.collection_id))

    # 3. Run tracking transfer (scalar fields + RunNote FK reassignment via bulk UPDATE)
    has_run_data = any(getattr(new, f) is not None for f in RUN_FIELDS)
    if not has_run_data:
        for field in RUN_FIELDS:
            old_val = getattr(old, field)
            if old_val is not None:
                setattr(new, field, old_val)

        # Reassign RunNote records via bulk UPDATE to avoid cascade delete-orphan
        from grimoire.models.run_note import RunNote
        await db.execute(
            sa_update(RunNote)
            .where(RunNote.product_id == old.id)
            .values(product_id=new.id)
        )

    # 4. Supersede the old product
    old.is_superseded = True
    old.superseded_by_id = new.id
    old.is_duplicate = False
    old.duplicate_of_id = None
    old.duplicate_reason = None

    await db.commit()

    return {"transferred_fields": transferred, "old_id": old.id, "new_id": new.id}


async def dismiss_revision(db: AsyncSession, old_product_id: int) -> None:
    """Dismiss a revision candidate: clear all duplicate/revision markers."""
    result = await db.execute(select(Product).where(Product.id == old_product_id))
    old = result.scalar_one_or_none()
    if not old:
        raise ValueError(f"Product {old_product_id} not found")

    old.is_duplicate = False
    old.duplicate_of_id = None
    old.duplicate_reason = None

    await db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/revision_service.py backend/tests/services/test_revision_service.py
git commit -m "feat(revision): add confirm/dismiss revision with metadata transfer"
```

---

### Task 7: Orphan Cleanup

**Files:**
- Modify: `backend/grimoire/services/revision_service.py`
- Modify: `backend/tests/services/test_revision_service.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/services/test_revision_service.py`:

```python
from grimoire.services.revision_service import cleanup_orphaned_superseded


@pytest.mark.asyncio
async def test_cleanup_orphaned_superseded(db):
    """If the newer product is deleted, clear superseded state on old products."""
    old = Product(
        file_path="/t/A.pdf", file_name="A.pdf", file_hash="aaa",
        file_size=100, normalized_stem="a", title="A",
    )
    newer = Product(
        file_path="/t/A_v2.pdf", file_name="A_v2.pdf", file_hash="bbb",
        file_size=200, normalized_stem="a", title="A v2",
    )
    db.add_all([old, newer])
    await db.flush()

    # Simulate a confirmed revision
    old.is_superseded = True
    old.superseded_by_id = newer.id
    await db.commit()

    # Delete the newer product (simulating user deletion)
    await db.delete(newer)
    await db.commit()

    result = await cleanup_orphaned_superseded(db)
    assert result["cleaned"] == 1

    await db.refresh(old)
    assert old.is_superseded is False
    assert old.superseded_by_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py::test_cleanup_orphaned_superseded -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement orphan cleanup**

Add to `backend/grimoire/services/revision_service.py`:

```python
async def cleanup_orphaned_superseded(db: AsyncSession) -> dict:
    """Clear is_superseded on products whose superseded_by target no longer exists."""
    # Find superseded products whose target doesn't exist
    subq = select(Product.id)
    result = await db.execute(
        select(Product).where(
            Product.is_superseded == True,
            Product.superseded_by_id.isnot(None),
            ~Product.superseded_by_id.in_(subq),
        )
    )
    orphans = result.scalars().all()

    for product in orphans:
        product.is_superseded = False
        product.superseded_by_id = None

    if orphans:
        await db.commit()

    return {"cleaned": len(orphans)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py::test_cleanup_orphaned_superseded -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/revision_service.py backend/tests/services/test_revision_service.py
git commit -m "feat(revision): add orphan cleanup for deleted superseding products"
```

---

## Chunk 3: Scanner Integration & API

### Task 8: Scanner Integration

**Files:**
- Modify: `backend/grimoire/services/scanner.py` (~line 138 for stem assignment, ~line 162 for revision detection pass)
- Modify: `backend/tests/services/test_revision_service.py`

- [ ] **Step 1: Write failing test for scanner setting normalized_stem**

Add to `backend/tests/services/test_revision_service.py`:

```python
from grimoire.services.scanner import scan_folder
from grimoire.models.watched_folder import WatchedFolder


@pytest.mark.asyncio
async def test_scanner_sets_normalized_stem(db, tmp_path):
    """Scanner populates normalized_stem on new products."""
    # Create a test PDF file (just needs to exist)
    pdf = tmp_path / "Monster_Manual-PDF.pdf"
    pdf.write_bytes(b"%PDF-1.4 test content")

    folder = WatchedFolder(path=str(tmp_path), label="test")
    db.add(folder)
    await db.commit()

    result = await scan_folder(db, folder)

    from sqlalchemy import select as sa_select
    products = (await db.execute(sa_select(Product))).scalars().all()
    assert len(products) >= 1
    product = next(p for p in products if "Monster_Manual" in p.file_name)
    assert product.normalized_stem == "monster_manual"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py::test_scanner_sets_normalized_stem -v`
Expected: FAIL — `normalized_stem` is None

- [ ] **Step 3: Modify scanner to set normalized_stem on product creation**

In `backend/grimoire/services/scanner.py`, at the product creation block (around line 138-146), add `normalized_stem`:

```python
from grimoire.services.revision_service import normalize_stem
```

At the Product() constructor (around line 138):
```python
normalized_stem=normalize_stem(pdf_path.name),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/services/test_revision_service.py::test_scanner_sets_normalized_stem -v`
Expected: PASS

- [ ] **Step 5: Add revision detection pass to scanner**

In `backend/grimoire/services/scanner.py`, after the existing `batch_check_and_mark_duplicates` call (around line 162), add:

```python
from grimoire.services.revision_service import mark_revision_candidates

revision_count = await mark_revision_candidates(db)
```

Update the scan result dict (around line 175-181) to include:
```python
"revision_candidates": revision_count,
```

- [ ] **Step 6: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/services/scanner.py backend/tests/services/test_revision_service.py
git commit -m "feat(revision): integrate stem normalization and revision detection into scanner"
```

---

### Task 9: Revision API Endpoints

**Files:**
- Modify: `backend/grimoire/api/routes/duplicates.py`
- Create: `backend/tests/api/test_revision_routes.py`

- [ ] **Step 1: Write failing tests for revision endpoints**

```python
# backend/tests/api/test_revision_routes.py
import pytest
from httpx import AsyncClient, ASGITransport
from grimoire.models.product import Product
from grimoire.main import app
from grimoire.database import get_db


@pytest.fixture
def client(db):
    """Create test client with DB dependency override."""
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_revision_groups(client, db):
    """GET /api/v1/duplicates?type=revision returns revision candidates."""
    old = Product(
        file_path="/t/A.pdf", file_name="A.pdf", file_hash="aaa",
        file_size=100, normalized_stem="a", title="A",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/A_v2.pdf", file_name="A_v2.pdf", file_hash="bbb",
        file_size=200, normalized_stem="a", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    async with client as c:
        resp = await c.get("/api/v1/duplicates", params={"type": "revision"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_confirm_revision_endpoint(client, db):
    """POST /api/v1/duplicates/{id}/confirm-revision supersedes the product."""
    old = Product(
        file_path="/t/A.pdf", file_name="A.pdf", file_hash="aaa",
        file_size=100, normalized_stem="a", title="A", author="Test Author",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/A_v2.pdf", file_name="A_v2.pdf", file_hash="bbb",
        file_size=200, normalized_stem="a", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    async with client as c:
        resp = await c.post(f"/api/v1/duplicates/{old.id}/confirm-revision")
    assert resp.status_code == 200

    await db.refresh(old)
    assert old.is_superseded is True


@pytest.mark.asyncio
async def test_dismiss_revision_endpoint(client, db):
    """POST /api/v1/duplicates/{id}/dismiss-revision clears revision marking."""
    old = Product(
        file_path="/t/A.pdf", file_name="A.pdf", file_hash="aaa",
        file_size=100, normalized_stem="a", title="A",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/A_v2.pdf", file_name="A_v2.pdf", file_hash="bbb",
        file_size=200, normalized_stem="a", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    async with client as c:
        resp = await c.post(f"/api/v1/duplicates/{old.id}/dismiss-revision")
    assert resp.status_code == 200

    await db.refresh(old)
    assert old.is_duplicate is False


@pytest.mark.asyncio
async def test_revision_stats(client, db):
    """GET /api/v1/duplicates/stats includes revision_candidates count."""
    old = Product(
        file_path="/t/A.pdf", file_name="A.pdf", file_hash="aaa",
        file_size=100, normalized_stem="a", title="A",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/A_v2.pdf", file_name="A_v2.pdf", file_hash="bbb",
        file_size=200, normalized_stem="a", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    async with client as c:
        resp = await c.get("/api/v1/duplicates/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "revision_candidates" in data
    assert data["revision_candidates"] >= 1


@pytest.mark.asyncio
async def test_scan_revisions(client, db):
    """POST /api/v1/duplicates/scan with type=revision runs revision detection."""
    p1 = Product(
        file_path="/t/Book.pdf", file_name="Book.pdf", file_hash="aaa",
        file_size=100, normalized_stem="book", title="Book",
    )
    p2 = Product(
        file_path="/t/Book_Revised.pdf", file_name="Book_Revised.pdf", file_hash="bbb",
        file_size=200, normalized_stem="book", title="Book Revised",
    )
    db.add_all([p1, p2])
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/duplicates/scan", params={"scan_type": "all"})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/api/test_revision_routes.py -v`
Expected: FAIL — 404/422 errors

- [ ] **Step 3: Add revision endpoints to duplicates router**

In `backend/grimoire/api/routes/duplicates.py`, add:

```python
from grimoire.services.revision_service import (
    get_revision_groups,
    confirm_revision,
    dismiss_revision,
    mark_revision_candidates,
)
```

Add a `type` query param to the existing `list_duplicate_groups` endpoint (around line 36):
```python
@router.get("")
async def list_duplicate_groups(
    type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if type == "revision":
        return await get_revision_groups(db)
    return await get_duplicate_groups(db)
```

Add new endpoints:
```python
@router.post("/{product_id}/confirm-revision")
async def confirm_revision_endpoint(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await confirm_revision(db, product_id)
    return result


@router.post("/{product_id}/dismiss-revision")
async def dismiss_revision_endpoint(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    await dismiss_revision(db, product_id)
    return {"status": "dismissed"}
```

Update stats endpoint to include revision count:
```python
# In duplicate_stats handler, add:
revision_count_result = await db.execute(
    select(func.count(Product.id)).where(Product.duplicate_reason == "revision")
)
revision_candidates = revision_count_result.scalar() or 0
# Add to returned dict: "revision_candidates": revision_candidates
```

Update scan endpoint to accept `scan_type` param:
```python
@router.post("/scan")
async def scan_duplicates(
    scan_type: str = "all",
    db: AsyncSession = Depends(get_db),
):
    result = {}
    if scan_type in ("hash", "all"):
        result["duplicates"] = await scan_for_duplicates(db)
    if scan_type in ("revision", "all"):
        result["revision_candidates"] = await mark_revision_candidates(db)
    return result
```

- [ ] **Step 4: Add `get_revision_groups` to revision_service.py**

```python
async def get_revision_groups(db: AsyncSession) -> list[dict]:
    """Get revision candidate groups for the API (already-marked candidates)."""
    result = await db.execute(
        select(Product).where(Product.duplicate_reason == "revision")
    )
    candidates = result.scalars().all()

    # Group by normalized_stem
    groups_by_stem: dict[str, list] = {}
    newer_ids = set()
    for c in candidates:
        stem = c.normalized_stem
        if stem not in groups_by_stem:
            groups_by_stem[stem] = []
        groups_by_stem[stem].append(c)
        if c.duplicate_of_id:
            newer_ids.add(c.duplicate_of_id)

    # Fetch the newer products
    if newer_ids:
        result = await db.execute(select(Product).where(Product.id.in_(newer_ids)))
        newer_products = {p.id: p for p in result.scalars().all()}
    else:
        newer_products = {}

    groups = []
    for stem, old_products in groups_by_stem.items():
        newer_id = old_products[0].duplicate_of_id
        newer = newer_products.get(newer_id)
        groups.append({
            "normalized_stem": stem,
            "newer": {
                "id": newer.id, "title": newer.title,
                "file_name": newer.file_name, "file_path": newer.file_path,
            } if newer else None,
            "older": [
                {
                    "id": p.id, "title": p.title,
                    "file_name": p.file_name, "file_path": p.file_path,
                }
                for p in old_products
            ],
        })

    return groups
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/api/test_revision_routes.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/api/routes/duplicates.py backend/grimoire/services/revision_service.py backend/tests/api/test_revision_routes.py
git commit -m "feat(revision): add revision API endpoints (list, confirm, dismiss, scan, stats)"
```

---

### Task 10: Visibility Filtering

**Files:**
- Modify: `backend/grimoire/api/routes/products.py` (~line 138)
- Modify: `backend/grimoire/services/sync_service.py` (~line 301)
- Modify: `backend/tests/api/test_revision_routes.py`

- [ ] **Step 1: Write failing test for product list filtering**

Add to `backend/tests/api/test_revision_routes.py`:

```python
@pytest.mark.asyncio
async def test_superseded_products_hidden_from_list(client, db):
    """GET /api/v1/products excludes superseded products."""
    visible = Product(
        file_path="/t/Visible.pdf", file_name="Visible.pdf", file_hash="aaa",
        file_size=100, normalized_stem="visible", title="Visible",
    )
    hidden = Product(
        file_path="/t/Hidden.pdf", file_name="Hidden.pdf", file_hash="bbb",
        file_size=200, normalized_stem="hidden", title="Hidden",
        is_superseded=True,
    )
    db.add_all([visible, hidden])
    await db.commit()

    resp = await client.get("/api/v1/products")
    assert resp.status_code == 200
    titles = [p["title"] for p in resp.json()["products"]]
    assert "Visible" in titles
    assert "Hidden" not in titles
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/test_revision_routes.py::test_superseded_products_hidden_from_list -v`
Expected: FAIL — "Hidden" appears in list

- [ ] **Step 3: Add `is_superseded` filter to product list**

In `backend/grimoire/api/routes/products.py`, at line 138, update the conditions list:

```python
conditions = [Product.is_duplicate == False, Product.is_missing == False, Product.is_superseded == False]
```

- [ ] **Step 4: Add visibility filtering to sync service**

In `backend/grimoire/services/sync_service.py`, wherever products are queried for contribution (around line 301-306), add visibility filters:

```python
.where(
    Product.is_duplicate == False,
    Product.is_missing == False,
    Product.is_superseded == False,
)
```

- [ ] **Step 5: Add is_superseded filtering to processing queue**

In `backend/grimoire/services/scanner.py`, where products are queued for processing, add `is_superseded == False` filter alongside the existing `is_duplicate` check. This prevents queuing tasks for superseded products.

- [ ] **Step 6: Protect revision candidates from hash-based scan clearing**

In `backend/grimoire/services/duplicate_service.py`, in `scan_for_duplicates()` (around line 226), add a condition to skip products with `duplicate_reason="revision"` when clearing/resetting duplicate flags. This prevents a hash-only scan from accidentally clearing revision candidate markers.

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/api/test_revision_routes.py -v`
Expected: ALL PASS

- [ ] **Step 8: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add backend/grimoire/api/routes/products.py backend/grimoire/services/sync_service.py backend/grimoire/services/scanner.py backend/grimoire/services/duplicate_service.py backend/tests/api/test_revision_routes.py
git commit -m "feat(revision): add is_superseded visibility filtering to product list, sync, queue, and hash-scan protection"
```

---

## Chunk 4: Frontend Integration

### Task 11: Revisions Tab in Duplicates View

**Files:**
- Modify: `frontend/src/pages/LibraryManagement.tsx`

- [ ] **Step 1: Add revision types and API hooks**

In `frontend/src/pages/LibraryManagement.tsx`, add interfaces and queries:

Add interface (after `DuplicateGroup` interface around line 56):
```typescript
interface RevisionGroup {
  normalized_stem: string;
  newer: { id: number; title: string; file_name: string; file_path: string } | null;
  older: { id: number; title: string; file_name: string; file_path: string }[];
}
```

Add to the `DuplicateStats` interface (around line 58):
```typescript
revision_candidates: number;
```

- [ ] **Step 2: Add revision query and mutations**

Add `useQuery` for revision groups (near existing duplicate queries around line 162):
```typescript
const { data: revisionGroups } = useQuery<RevisionGroup[]>({
  queryKey: ['revision-groups'],
  queryFn: () => api.get('/duplicates?type=revision').then(r => r.data),
  enabled: /* enabled when revisions sub-tab is active */,
});
```

Add mutations for confirm/dismiss:
```typescript
const confirmRevisionMutation = useMutation({
  mutationFn: (productId: number) => api.post(`/duplicates/${productId}/confirm-revision`),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['revision-groups'] });
    queryClient.invalidateQueries({ queryKey: ['duplicate-stats'] });
    queryClient.invalidateQueries({ queryKey: ['products'] });
  },
});

const dismissRevisionMutation = useMutation({
  mutationFn: (productId: number) => api.post(`/duplicates/${productId}/dismiss-revision`),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['revision-groups'] });
    queryClient.invalidateQueries({ queryKey: ['duplicate-stats'] });
  },
});
```

- [ ] **Step 3: Add revisions filter/tab to the duplicates section**

Within the duplicates tab section (around line 603), add a sub-filter to toggle between "Hash Duplicates" and "Revisions":

```typescript
// State for sub-filter
const [duplicateView, setDuplicateView] = useState<'hash' | 'revision'>('hash');
```

Add filter buttons and render revision groups when `duplicateView === 'revision'`:
```tsx
{/* Sub-filter tabs */}
<div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
  <button
    onClick={() => setDuplicateView('hash')}
    style={{
      padding: '6px 16px',
      background: duplicateView === 'hash' ? 'var(--color-primary)' : 'var(--color-surface)',
      color: duplicateView === 'hash' ? 'var(--color-on-primary)' : 'var(--color-text)',
      border: '1px solid var(--color-border)',
      borderRadius: '4px',
      cursor: 'pointer',
    }}
  >
    Duplicates {stats?.duplicate_groups ? `(${stats.duplicate_groups})` : ''}
  </button>
  <button
    onClick={() => setDuplicateView('revision')}
    style={{
      padding: '6px 16px',
      background: duplicateView === 'revision' ? 'var(--color-primary)' : 'var(--color-surface)',
      color: duplicateView === 'revision' ? 'var(--color-on-primary)' : 'var(--color-text)',
      border: '1px solid var(--color-border)',
      borderRadius: '4px',
      cursor: 'pointer',
    }}
  >
    Revisions {stats?.revision_candidates ? `(${stats.revision_candidates})` : ''}
  </button>
</div>
```

- [ ] **Step 4: Render revision groups**

```tsx
{duplicateView === 'revision' && revisionGroups && (
  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
    {revisionGroups.length === 0 ? (
      <p style={{ color: 'var(--color-text-secondary)' }}>No revision candidates found.</p>
    ) : (
      revisionGroups.map((group) => (
        <div
          key={group.normalized_stem}
          style={{
            border: '1px solid var(--color-border)',
            borderRadius: '8px',
            padding: '16px',
            background: 'var(--color-surface)',
          }}
        >
          <h4 style={{ margin: '0 0 8px 0', color: 'var(--color-text)' }}>
            {group.newer?.title || group.normalized_stem}
          </h4>
          {group.newer && (
            <div style={{ marginBottom: '8px', color: 'var(--color-text-secondary)', fontSize: '0.9em' }}>
              <strong>Newer:</strong> {group.newer.file_name}
            </div>
          )}
          {group.older.map((old) => (
            <div
              key={old.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px',
                borderTop: '1px solid var(--color-border)',
              }}
            >
              <div>
                <span style={{ color: 'var(--color-text-secondary)', fontSize: '0.9em' }}>
                  Older: {old.file_name}
                </span>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={() => confirmRevisionMutation.mutate(old.id)}
                  disabled={confirmRevisionMutation.isPending}
                  style={{
                    padding: '4px 12px',
                    background: 'var(--color-success)',
                    color: 'white',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer',
                  }}
                >
                  Confirm
                </button>
                <button
                  onClick={() => dismissRevisionMutation.mutate(old.id)}
                  disabled={dismissRevisionMutation.isPending}
                  style={{
                    padding: '4px 12px',
                    background: 'var(--color-surface)',
                    color: 'var(--color-text)',
                    border: '1px solid var(--color-border)',
                    borderRadius: '4px',
                    cursor: 'pointer',
                  }}
                >
                  Dismiss
                </button>
              </div>
            </div>
          ))}
        </div>
      ))
    )}
  </div>
)}
```

- [ ] **Step 5: Update scan button to use scan_type=all**

Update the `scanDuplicatesMutation` (around line 288) to pass `scan_type=all`:
```typescript
mutationFn: () => api.post('/duplicates/scan?scan_type=all'),
```

Also invalidate revision queries on scan success:
```typescript
onSuccess: () => {
  // existing invalidations...
  queryClient.invalidateQueries({ queryKey: ['revision-groups'] });
},
```

- [ ] **Step 6: Manual test in browser**

1. Start the app: `start.bat`
2. Navigate to Library Management → Duplicates tab
3. Verify "Duplicates" and "Revisions" sub-tabs appear
4. Click "Scan for Duplicates" — should run both hash and revision detection
5. If revision candidates exist, verify Confirm and Dismiss buttons work

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/LibraryManagement.tsx
git commit -m "feat(revision): add revisions tab to duplicates view with confirm/dismiss actions"
```

---

## Chunk 5: Final Integration & Cleanup

### Task 12: End-to-End Integration Test

**Files:**
- Create: `backend/tests/services/test_revision_e2e.py`

- [ ] **Step 1: Write end-to-end test**

```python
# backend/tests/services/test_revision_e2e.py
"""End-to-end test: full lifecycle of revision detection → confirm → verify."""
import pytest
from sqlalchemy import select
from grimoire.models.product import Product
from grimoire.services.revision_service import (
    mark_revision_candidates,
    confirm_revision,
    get_revision_groups,
    cleanup_orphaned_superseded,
)


@pytest.mark.asyncio
async def test_full_revision_lifecycle(db):
    """Complete flow: create products → detect → confirm → verify visibility."""
    # 1. Create two products that are revisions of each other
    old = Product(
        file_path="/lib/Curse_of_Strahd-PDF.pdf",
        file_name="Curse_of_Strahd-PDF.pdf",
        file_hash="hash_original",
        file_size=50000,
        normalized_stem="curse_of_strahd",
        title="Curse of Strahd",
        author="Wizards",
        publisher="WotC",
        game_system="D&D 5e",
    )
    revised = Product(
        file_path="/lib/Curse_of_Strahd-PDF_(Revised).pdf",
        file_name="Curse_of_Strahd-PDF_(Revised).pdf",
        file_hash="hash_revised",
        file_size=55000,
        normalized_stem="curse_of_strahd",
        title=None,  # Not yet identified
    )
    db.add_all([old, revised])
    await db.commit()

    # 2. Detect candidates
    count = await mark_revision_candidates(db)
    assert count == 1

    await db.refresh(old)
    assert old.is_duplicate is True
    assert old.duplicate_reason == "revision"
    assert old.duplicate_of_id == revised.id  # revised is newer (has indicator)

    # 3. Check groups API
    groups = await get_revision_groups(db)
    assert len(groups) == 1

    # 4. Confirm the revision
    result = await confirm_revision(db, old.id)
    assert "author" in result["transferred_fields"]

    await db.refresh(revised)
    assert revised.author == "Wizards"
    assert revised.publisher == "WotC"
    assert revised.game_system == "D&D 5e"
    assert revised.title == "Curse of Strahd"  # Transferred from old since revised.title was None

    await db.refresh(old)
    assert old.is_superseded is True
    assert old.is_duplicate is False

    # 5. Verify superseded product is not in visible queries
    visible = await db.execute(
        select(Product).where(Product.is_superseded == False, Product.is_missing == False)
    )
    visible_products = visible.scalars().all()
    assert old.id not in [p.id for p in visible_products]
    assert revised.id in [p.id for p in visible_products]

    # 6. Test orphan cleanup
    await db.delete(revised)
    await db.commit()

    cleanup = await cleanup_orphaned_superseded(db)
    assert cleanup["cleaned"] == 1

    await db.refresh(old)
    assert old.is_superseded is False
```

- [ ] **Step 2: Run the test**

Run: `cd backend && python -m pytest tests/services/test_revision_e2e.py -v`
Expected: ALL PASS

- [ ] **Step 3: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add backend/tests/services/test_revision_e2e.py
git commit -m "test(revision): add end-to-end integration test for full revision lifecycle"
```
