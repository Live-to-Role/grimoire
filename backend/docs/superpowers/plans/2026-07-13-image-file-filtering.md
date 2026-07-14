# Image-File Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep map/tile/stock-art PDFs out of text & OCR processing by fixing the filename classifier (word-boundary bug + missing keywords + publisher blacklist) and reclassifying the ~323 already-queued map files.

**Architecture:** All detection changes live in `processors/image_classifier.py`. The existing pipeline (`handle_text_task` in `queue_processor.py`) already diverts any product `detect_image_content()` flags — so improving the classifier automatically fixes live scans with no hot-path edits. A new backlog endpoint runs the improved classifier over pending queue items and diverts confirmed maps to image extraction.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, pytest + pytest-asyncio, PyMuPDF (fitz).

## Global Constraints

- Test runner is miniconda `python -m pytest` run from the `backend/` directory (NOT `.venv`, which lacks pytest). 7 pre-existing test failures are the accepted baseline — do not treat them as regressions.
- Route handlers commit explicitly; `get_db()` does not auto-commit.
- Blacklist hits are **decisive**: classify as `Map`, set `is_image_content=True`, and skip content analysis entirely (no PDF file open). Keyword/regex hits keep the existing two-tier content confirmation (≥50% image-dominant pages).
- Blacklist seed list (exact, lowercase substrings, matched against the normalized path+filename): `heroic maps`, `map alchemists`, `black scrolls games`, `0one games`, `animated dungeon maps`.
- Action on a detected map is unchanged existing behavior: flag `is_image_content`, queue an `extract_images` task (priority 2), auto-tag `Map`, skip text/OCR.

---

### Task 1: `_normalize_for_matching` helper

**Files:**
- Modify: `backend/grimoire/processors/image_classifier.py`
- Test: `backend/tests/test_image_classifier.py`

**Interfaces:**
- Produces: `_normalize_for_matching(text: str) -> str` — inserts a space at camelCase transitions and converts `_`/`-` to spaces. Used by `classify_by_name` and `matches_image_publisher`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_image_classifier.py`:

```python
from grimoire.processors.image_classifier import _normalize_for_matching


def test_normalize_splits_camelcase():
    assert _normalize_for_matching("HeroicMaps") == "Heroic Maps"


def test_normalize_treats_separators_as_spaces():
    assert _normalize_for_matching("Village_tiles-pack") == "Village tiles pack"


def test_normalize_leaves_plain_words():
    assert _normalize_for_matching("forest river") == "forest river"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `python -m pytest tests/test_image_classifier.py::test_normalize_splits_camelcase -v`
Expected: FAIL with `ImportError: cannot import name '_normalize_for_matching'`

- [ ] **Step 3: Write minimal implementation**

In `backend/grimoire/processors/image_classifier.py`, add after the `_BOOK_INDICATORS` list (around line 48):

```python
def _normalize_for_matching(text: str) -> str:
    """Normalize a filename/path for keyword and publisher matching.

    Inserts a space at camelCase boundaries so 'HeroicMaps' becomes
    'Heroic Maps' (fixing word-boundary regex misses on concatenated
    publisher names), and treats '_' and '-' as spaces.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    spaced = re.sub(r"[_\-]+", " ", spaced)
    return spaced
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `python -m pytest tests/test_image_classifier.py -v`
Expected: PASS (all existing + 3 new tests)

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/processors/image_classifier.py backend/tests/test_image_classifier.py
git commit -m "feat(classifier): add _normalize_for_matching for camelCase/separator normalization"
```

---

### Task 2: Publisher blacklist + `matches_image_publisher`

**Files:**
- Modify: `backend/grimoire/processors/image_classifier.py`
- Test: `backend/tests/test_image_classifier.py`

**Interfaces:**
- Consumes: `_normalize_for_matching(text: str) -> str` (Task 1).
- Produces:
  - `_IMAGE_CONTENT_PUBLISHERS: list[str]` — lowercase substrings.
  - `matches_image_publisher(filename: str, file_path: str) -> bool` — True if the normalized `"{filename} {file_path}"` contains any blacklist substring.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_image_classifier.py`:

```python
from grimoire.processors.image_classifier import matches_image_publisher


def test_publisher_match_on_folder_path():
    # Real DB path form: folder 'Heroic Maps', filename 'HeroicMaps_*'
    assert matches_image_publisher(
        "HeroicMaps_FireWyrm_GRID.pdf",
        r"D:\Drivethrurpg\Heroic Maps\HeroicMaps_FireWyrm_GRID.pdf",
    )


def test_publisher_match_camelcase_filename_only():
    # Even without the folder, the camelCase filename normalizes to a hit
    assert matches_image_publisher("HeroicMaps_Cliffs.pdf", "/misc/HeroicMaps_Cliffs.pdf")


def test_publisher_match_0one_games():
    assert matches_image_publisher("dungeon.pdf", r"D:\Drivethrurpg\0one Games\dungeon.pdf")


def test_publisher_no_match_regular_book():
    assert not matches_image_publisher(
        "Players_Handbook.pdf", r"D:\Drivethrurpg\Wizards\Players_Handbook.pdf"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `python -m pytest tests/test_image_classifier.py::test_publisher_match_on_folder_path -v`
Expected: FAIL with `ImportError: cannot import name 'matches_image_publisher'`

- [ ] **Step 3: Write minimal implementation**

In `backend/grimoire/processors/image_classifier.py`, add after `_normalize_for_matching` (from Task 1):

```python
# Known all-image-content publishers. A path/filename match is DECISIVE:
# classify as Map with no content analysis. Append as more are found.
_IMAGE_CONTENT_PUBLISHERS = [
    "heroic maps",
    "map alchemists",
    "black scrolls games",
    "0one games",
    "animated dungeon maps",
]


def matches_image_publisher(filename: str, file_path: str) -> bool:
    """True if the file lives under (or is named after) a known all-image
    publisher. Matches lowercase blacklist substrings against the normalized
    path+filename so one entry catches both 'Heroic Maps' folders and
    'HeroicMaps' filenames."""
    normalized = _normalize_for_matching(f"{filename} {file_path}").lower()
    return any(pub in normalized for pub in _IMAGE_CONTENT_PUBLISHERS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `python -m pytest tests/test_image_classifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/processors/image_classifier.py backend/tests/test_image_classifier.py
git commit -m "feat(classifier): add image-content publisher blacklist"
```

---

### Task 3: Wire blacklist + keywords into classification

**Files:**
- Modify: `backend/grimoire/processors/image_classifier.py:24-63` (`_CLASSIFICATION_RULES`, `classify_by_name`) and `detect_image_content` (around line 105)
- Test: `backend/tests/test_image_classifier.py`

**Interfaces:**
- Consumes: `_normalize_for_matching` (Task 1), `matches_image_publisher` (Task 2).
- Produces: `detect_image_content(...)` returns `is_image_content=True, classification="Map"` immediately for publisher matches; `classify_by_name` uses normalized text and returns `"Map"` for publisher matches.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_image_classifier.py`:

```python
from grimoire.processors import image_classifier
from grimoire.processors.image_classifier import detect_image_content


def test_classify_heroicmaps_camelcase_now_matches():
    # Regression: '\bmaps\b' previously missed 'HeroicMaps'
    assert classify_by_name("HeroicMaps_FireWyrm_GRID.pdf", "/x/HeroicMaps_FireWyrm_GRID.pdf") == "Map"


def test_classify_tiles_keyword():
    assert classify_by_name("Village_tiles.pdf", "/x/Village_tiles.pdf") == "Map"


def test_classify_no_signal_still_none():
    assert classify_by_name("Forest_river.pdf", "/x/Forest_river.pdf") is None


def test_detect_blacklist_short_circuits_without_opening_file(monkeypatch):
    # If content analysis were reached it would run on a missing path and return
    # is_image_content=False. A True result proves the blacklist short-circuited.
    def _boom(*a, **k):
        raise AssertionError("_analyze_content must not be called for blacklist hits")
    monkeypatch.setattr(image_classifier, "_analyze_content", _boom)

    result = detect_image_content(
        "/does/not/exist.pdf",
        "HeroicMaps_Cliffs.pdf",
        r"D:\Drivethrurpg\Heroic Maps\HeroicMaps_Cliffs.pdf",
    )
    assert result["is_image_content"] is True
    assert result["classification"] == "Map"


def test_detect_keyword_but_text_heavy_not_diverted(monkeypatch):
    # Name matches 'map' keyword but content is mostly text -> NOT image content.
    monkeypatch.setattr(
        image_classifier,
        "_analyze_content",
        lambda *a, **k: {
            "total_pages": 100, "pages_sampled": 10,
            "image_dominant_pages": 1, "total_images": 2,
            "total_text_chars": 50000, "avg_chars_per_page": 5000,
        },
    )
    result = detect_image_content(
        "/x/Dungeon_Map_Guide.pdf",
        "Dungeon_Map_Guide.pdf",
        "/x/Dungeon_Map_Guide.pdf",
    )
    assert result["is_image_content"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `python -m pytest tests/test_image_classifier.py::test_classify_heroicmaps_camelcase_now_matches tests/test_image_classifier.py::test_detect_blacklist_short_circuits_without_opening_file -v`
Expected: FAIL (`classify_by_name` returns None for HeroicMaps; blacklist not short-circuited yet)

- [ ] **Step 3: Write the implementation**

In `backend/grimoire/processors/image_classifier.py`:

(a) Extend the `Map` rule in `_CLASSIFICATION_RULES` (lines 25-29) — add tile/geomorph/grid markers:

```python
    ("Map", [
        r"\bmap\b", r"\bmaps\b", r"cartograph", r"battlemap", r"battle\s*map",
        r"dungeon\s*map", r"floorplan", r"floor\s*plan", r"overland\s*map",
        r"world\s*map", r"city\s*map", r"town\s*map", r"hex\s*map",
        r"\btile\b", r"\btiles\b", r"geomorph", r"\bgrid\b",
    ]),
```

> Note: `_normalize_for_matching` splits `NoGRID` into `No GRID`, so `\bgrid\b`
> already catches both `GRID` and `NoGRID` filename variants — no separate
> `nogrid` pattern is needed.

(b) Normalize + blacklist-first in `classify_by_name` (replace its body, lines 50-63):

```python
def classify_by_name(filename: str, file_path: str) -> str | None:
    """
    Check filename/path for image content keywords.

    Returns classification label if matched, None if no match.
    """
    if matches_image_publisher(filename, file_path):
        return "Map"

    search_text = _normalize_for_matching(f"{filename} {file_path}")

    for label, patterns in _CLASSIFICATION_RULES:
        for pattern in patterns:
            if re.search(pattern, search_text, re.IGNORECASE):
                return label

    return None
```

(c) Short-circuit in `detect_image_content` — insert as the first statement inside the function body, immediately after the docstring (before `name_classification = classify_by_name(...)` around line 105):

```python
    # Known image-content publishers are decisive: classify as Map with no
    # content analysis and no file open. Accepts a small false-positive risk.
    if matches_image_publisher(filename, file_path):
        return {
            "is_image_content": True,
            "classification": "Map",
            "reason": "Matched known image-content publisher",
            "stats": {},
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `python -m pytest tests/test_image_classifier.py -v`
Expected: PASS (all existing + new). The existing `test_false_positives_from_user_report` must still pass — the DCC/Silam/Tome/Crowdfund names contain no map keyword and no blacklist publisher.

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/processors/image_classifier.py backend/tests/test_image_classifier.py
git commit -m "feat(classifier): blacklist short-circuit + tile/geomorph/grid keywords + normalized matching"
```

---

### Task 4: Backlog reclassify endpoint

**Files:**
- Modify: `backend/grimoire/api/routes/queue.py` (add endpoint near `reclassify_failures`, ~line 419)
- Test: `backend/tests/api/test_reclassify_pending_maps.py` (create)

**Interfaces:**
- Consumes: `detect_image_content` / `matches_image_publisher` (Task 3); `set_content_type_tag` from `grimoire.services.tag_service`.
- Produces: `POST /api/v1/queue/reclassify-pending-maps` returning `{"diverted": int, "scanned": int}`. For each confirmed map it deletes the pending `text`/`ocr_text` row, sets `is_image_content=True` + `product_type="Map"` + Map tag, and queues one `extract_images` task (priority 2) if none pending/processing.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/test_reclassify_pending_maps.py`:

```python
"""POST /queue/reclassify-pending-maps diverts blacklisted/keyword maps off the text queue."""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from grimoire.main import app
from grimoire.database import get_db
from grimoire.models.product import Product
from grimoire.models import ProcessingQueue


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reclassify_pending_maps_diverts_blacklist(client, db):
    # Blacklisted publisher -> diverted with no file open
    hmap = Product(file_path=r"D:\Drivethrurpg\Heroic Maps\HeroicMaps_Cliffs.pdf",
                   file_name="HeroicMaps_Cliffs.pdf", file_size=1, file_hash="h1")
    # Regular book -> untouched
    book = Product(file_path=r"D:\Drivethrurpg\Wizards\Players_Handbook.pdf",
                   file_name="Players_Handbook.pdf", file_size=1, file_hash="h2")
    db.add_all([hmap, book])
    await db.commit()

    db.add_all([
        ProcessingQueue(product_id=hmap.id, task_type="text", status="pending"),
        ProcessingQueue(product_id=book.id, task_type="text", status="pending"),
    ])
    await db.commit()

    async with client as c:
        resp = await c.post("/api/v1/queue/reclassify-pending-maps")
    assert resp.status_code == 200
    body = resp.json()
    assert body["diverted"] == 1

    await db.refresh(hmap)
    await db.refresh(book)
    assert hmap.is_image_content is True
    assert hmap.product_type == "Map"
    assert book.is_image_content in (False, None)

    # hmap's pending text row is gone; an extract_images row exists
    hmap_rows = (await db.execute(
        select(ProcessingQueue).where(ProcessingQueue.product_id == hmap.id)
    )).scalars().all()
    types = sorted(r.task_type for r in hmap_rows)
    assert types == ["extract_images"]

    # book's text row remains pending
    book_rows = (await db.execute(
        select(ProcessingQueue).where(ProcessingQueue.product_id == book.id)
    )).scalars().all()
    assert [r.task_type for r in book_rows] == ["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `python -m pytest tests/api/test_reclassify_pending_maps.py -v`
Expected: FAIL with 404 (endpoint does not exist yet)

- [ ] **Step 3: Write the implementation**

In `backend/grimoire/api/routes/queue.py`, add after `reclassify_failures` (after line 418):

```python
@router.post("/reclassify-pending-maps")
async def reclassify_pending_maps(db: DbSession) -> dict:
    """Scan pending text/ocr_text items and divert confirmed map/image files to
    image extraction. Blacklisted publishers divert with no file open; keyword
    hits are content-confirmed by detect_image_content."""
    from pathlib import Path
    from grimoire.processors.image_classifier import (
        detect_image_content,
        matches_image_publisher,
    )
    from grimoire.services.tag_service import set_content_type_tag

    result = await db.execute(
        select(ProcessingQueue).where(
            ProcessingQueue.status == "pending",
            ProcessingQueue.task_type.in_(["text", "ocr_text"]),
        )
    )
    items = list(result.scalars().all())

    product_ids = {item.product_id for item in items}
    products: dict[int, Product] = {}
    if product_ids:
        prod_result = await db.execute(select(Product).where(Product.id.in_(product_ids)))
        products = {p.id: p for p in prod_result.scalars().all()}

    diverted = 0
    for item in items:
        product = products.get(item.product_id)
        if product is None:
            continue

        if matches_image_publisher(product.file_name, product.file_path):
            classification = "Map"
        else:
            detection = detect_image_content(
                Path(product.file_path), product.file_name, product.file_path
            )
            if not detection["is_image_content"]:
                continue
            classification = detection["classification"] or "Map"

        product.is_image_content = True
        product.product_type = classification
        await set_content_type_tag(db, product.id, classification)

        await db.delete(item)

        existing = await db.execute(
            select(ProcessingQueue).where(
                ProcessingQueue.product_id == product.id,
                ProcessingQueue.task_type == "extract_images",
                ProcessingQueue.status.in_(["pending", "processing"]),
            )
        )
        if not existing.scalar_one_or_none():
            db.add(ProcessingQueue(
                product_id=product.id,
                task_type="extract_images",
                priority=2,
                status="pending",
            ))
        diverted += 1

    await db.commit()
    return {"diverted": diverted, "scanned": len(items)}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `backend/`): `python -m pytest tests/api/test_reclassify_pending_maps.py -v`
Expected: PASS

- [ ] **Step 5: Run the full classifier + queue test suites**

Run (from `backend/`): `python -m pytest tests/test_image_classifier.py tests/api/test_reclassify_pending_maps.py tests/api/test_reclassify_failures.py -v`
Expected: PASS (no regressions in neighboring reclassify tests)

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/api/routes/queue.py backend/tests/api/test_reclassify_pending_maps.py
git commit -m "feat(queue): reclassify-pending-maps endpoint to divert queued maps off text/OCR"
```

---

## Post-implementation (manual, not a code task)

After merge, trigger the backlog pass once against the running app to clear the
~323 queued map files (and verify the count):

```
POST /api/v1/queue/reclassify-pending-maps
```

Expect ~323 `diverted` for the five seeded publishers (285 of them Heroic Maps).
A frontend button can be wired later alongside the existing reclassify actions;
not required for this plan.

## Notes on scope

- No change to `handle_text_task` is needed — it already calls
  `detect_image_content` and diverts, so live scans of blacklisted publishers are
  fixed by Task 3 automatically.
- Zip-archive scanning (~3,139 unscanned archives) is a separate spec, out of
  scope here.
