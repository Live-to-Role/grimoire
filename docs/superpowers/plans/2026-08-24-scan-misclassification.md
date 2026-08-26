# Scan Misclassification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user mark misclassified scanned books from the Gallery so they get OCR'd, track which products have been reviewed, and stop Grimoire uploading cover artwork it shouldn't.

**Architecture:** Two new `Product` columns separate "is a collection of images" from "is a document whose pages are images", and record a human verdict. The Gallery gains multi-select with two actions and a needs-review filter. The existing bulk un-flag path — which today clears the flag but never queues extraction — is fixed once, serving both the Gallery and the Library. Two independent rules drop cover images from Codex contributions.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, SQLite/aiosqlite, pytest + pytest-asyncio (`asyncio_mode = "auto"`), React 18 + TypeScript, React Query v5, Tailwind with CSS-variable theming.

**Spec:** `docs/superpowers/specs/2026-08-24-scan-misclassification-design.md`

## Global Constraints

- Tests run with miniconda `python -m pytest` from `backend/`, **not** `.venv` (which lacks pytest).
- Baseline before this work: **586 passed, 1 failed**. The failure is
  `tests/api/test_browse.py::test_browse_falls_back_when_home_is_unavailable`, which
  fails identically on a clean tree. Do not try to fix it; do not let the count drop.
- Route handlers commit explicitly — `get_db()` does not auto-commit.
- New columns are added via `_ensure_columns` in `backend/grimoire/database.py`, not Alembic.
- Frontend has no test harness. `npx tsc -b` from `frontend/` is the gate.
- NavRail and Gallery use CSS variables (`var(--color-*)`), not Tailwind color utilities.
- The classifier (`image_classifier.py`) is **not** modified by this plan. That is a deliberate spec decision.

---

### Task 1: Add `is_scanned` and `classification_reviewed_at` columns

**Files:**
- Modify: `backend/grimoire/models/product.py:99-102`
- Modify: `backend/grimoire/database.py:146-159`
- Test: `backend/tests/models/test_scan_columns.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Product.is_scanned: bool` (default `False`), `Product.classification_reviewed_at: datetime | None`.

- [x] **Step 1: Write the failing test**

Create `backend/tests/models/test_scan_columns.py`:

```python
"""`is_image_content` and `is_scanned` are different facts.

A collection of images (a map pack) and a document whose pages are images (a
scanned module) were conflated, so scanned books were routed to image
extraction and never OCR'd. `is_scanned` survives the image flag being
cleared; `classification_reviewed_at` records that a human judged the product,
which is what lets the review backlog shrink.
"""
import pytest
from sqlalchemy import select

from grimoire.models import Product


def _product(**kw):
    base = dict(
        file_path=r"D:\Games\thing.pdf",
        file_name="thing.pdf",
        file_size=1024,
        file_hash="h",
        title="A Thing",
    )
    base.update(kw)
    return Product(**base)


@pytest.mark.asyncio
async def test_is_scanned_defaults_to_false(db):
    product = _product()
    db.add(product)
    await db.commit()

    stored = (await db.execute(select(Product))).scalar_one()
    assert stored.is_scanned is False
    assert stored.classification_reviewed_at is None


@pytest.mark.asyncio
async def test_a_product_can_be_scanned_without_being_image_content(db):
    """The state a rescued scan ends in: OCR-routed, out of the gallery."""
    from datetime import datetime, UTC

    product = _product(is_image_content=False, is_scanned=True,
                       classification_reviewed_at=datetime.now(UTC))
    db.add(product)
    await db.commit()

    stored = (await db.execute(select(Product))).scalar_one()
    assert stored.is_scanned is True
    assert stored.is_image_content is False
    assert stored.classification_reviewed_at is not None
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/models/test_scan_columns.py -q`
Expected: FAIL with `TypeError: 'is_scanned' is an invalid keyword argument for Product`

- [x] **Step 3: Add the columns to the model**

In `backend/grimoire/models/product.py`, after the `image_count` line (currently `:102`):

```python
    # A document whose pages are images — a scan — as opposed to a collection
    # of images. `is_image_content` conflated the two, so scanned books were
    # routed to image extraction and never OCR'd. This survives the image flag
    # being cleared, so it can drive the OCR route and gate cover sharing.
    is_scanned: Mapped[bool] = mapped_column(Boolean, default=False)

    # When a human last judged this product's classification, whichever way
    # they judged it. Without this there is no way to tell reviewed products
    # from unreviewed ones, and a ~971-product backlog cannot be worked
    # through without re-covering ground.
    classification_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
```

Confirm `datetime` and `DateTime` are already imported in that file; if not, add
`from datetime import datetime` and include `DateTime` in the existing
`from sqlalchemy import ...` line.

- [x] **Step 4: Add the columns to `_ensure_columns`**

In `backend/grimoire/database.py`, add to the `migrations` list (after the
`product_embeddings` entries):

```python
        ("products", "is_scanned", "BOOLEAN DEFAULT 0"),
        ("products", "classification_reviewed_at", "DATETIME"),
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/models/test_scan_columns.py -q`
Expected: 2 passed

- [x] **Step 6: Run the full suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: 588 passed, 1 failed (the known `test_browse` failure)

- [x] **Step 7: Commit**

```bash
git add backend/grimoire/models/product.py backend/grimoire/database.py backend/tests/models/test_scan_columns.py
git commit -m "feat(products): separate is_scanned from is_image_content

A collection of images and a document whose pages are images are different
facts, and conflating them is why scanned modules were routed to image
extraction and never OCR'd. is_scanned survives the image flag being cleared,
so it can drive the OCR route and gate cover sharing.

classification_reviewed_at records that a human judged the product, whichever
way. A ~971-product review backlog cannot be worked through without a way to
tell reviewed from unreviewed."
```

---

### Task 2: Un-flagging queues OCR and records the verdict

**Files:**
- Modify: `backend/grimoire/api/routes/bulk.py:288-311`
- Test: `backend/tests/api/test_bulk_unflag_queues_ocr.py`

**Interfaces:**
- Consumes: `Product.is_scanned`, `Product.classification_reviewed_at` (Task 1).
- Produces: a `ProcessingQueue` row with `task_type="ocr_text"`, `priority=3`, `status="pending"` for each un-flagged product.

This is the fix that makes everything else worth doing: today un-flagging deletes
the extracted images and never gets you the text.

- [x] **Step 1: Write the failing test**

Create `backend/tests/api/test_bulk_unflag_queues_ocr.py`:

```python
"""Un-flagging an image-content product must actually get you the text.

`bulk.py`'s un-flag branch clears the flag, nulls product_type, deletes the
extracted images from disk and removes content-type tags — but never queued
text extraction. So the one action a user has for "this is really a document"
lost the images without gaining the text.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from grimoire.database import get_db
from grimoire.main import app
from grimoire.models import ProcessingQueue, Product


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def flagged(db):
    product = Product(
        file_path=r"D:\Games\SF1 Volturnus.pdf",
        file_name="SF1 Volturnus.pdf",
        file_size=7_000_000,
        file_hash="f46e13f8",
        title="SF1 Volturnus Planet of Mystery",
        product_type="Map",
        is_image_content=True,
        images_extracted=True,
        image_count=36,
        page_count=36,
    )
    db.add(product)
    await db.commit()
    return product


@pytest.mark.asyncio
async def test_unflagging_queues_ocr(client, db, flagged):
    response = await client.post(
        "/api/v1/bulk/update",
        json={"product_ids": [flagged.id], "is_image_content": False},
    )

    assert response.status_code == 200
    queued = (await db.execute(
        select(ProcessingQueue).where(ProcessingQueue.product_id == flagged.id)
    )).scalars().all()
    assert [q.task_type for q in queued] == ["ocr_text"]


@pytest.mark.asyncio
async def test_unflagging_marks_it_scanned_and_reviewed(client, db, flagged):
    await client.post(
        "/api/v1/bulk/update",
        json={"product_ids": [flagged.id], "is_image_content": False},
    )

    assert flagged.is_scanned is True
    assert flagged.classification_reviewed_at is not None
    assert flagged.is_image_content is False


@pytest.mark.asyncio
async def test_unflagging_still_clears_the_existing_fields(client, db, flagged):
    """Destructive semantics are unchanged — one code path with the Library."""
    await client.post(
        "/api/v1/bulk/update",
        json={"product_ids": [flagged.id], "is_image_content": False},
    )

    assert flagged.product_type is None
    assert flagged.images_extracted is False
    assert flagged.image_count is None


@pytest.mark.asyncio
async def test_a_rescued_scan_becomes_codex_eligible(client, db, flagged):
    """Phase 3 made image-content products ineligible to contribute. A scan
    misclassified as image content inherited that, so rescuing it has to give
    the eligibility back — otherwise the fix leaves a second wrong answer."""
    from grimoire.services.codex_eligibility import is_codex_eligible

    assert is_codex_eligible(flagged)[0] is False

    await client.post(
        "/api/v1/bulk/update",
        json={"product_ids": [flagged.id], "is_image_content": False},
    )

    assert is_codex_eligible(flagged) == (True, "eligible")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/api/test_bulk_unflag_queues_ocr.py -q`
Expected: 3 FAIL (`assert [] == ['ocr_text']`, `assert False is True`, and the
eligibility test, since `product_type` is cleared but `is_image_content` is not
what the predicate reads first), 1 PASS
(`test_unflagging_still_clears_the_existing_fields` — that behaviour already
exists and is a guard rail proving this change does not alter it)

- [x] **Step 3: Extend the un-flag branch**

In `backend/grimoire/api/routes/bulk.py`, replace the loop body in the
`is_image_content is False` branch (currently `:288-297`):

```python
    elif "is_image_content" in provided_fields and request.is_image_content is False:
        from datetime import datetime, UTC

        from grimoire.models import ProcessingQueue
        from grimoire.services.tag_service import remove_content_type_tags

        for product in products:
            product.is_image_content = False
            product.product_type = None
            product.images_extracted = False
            product.image_count = None
            # The point of un-flagging is to get the text. This never queued
            # anything, so the action deleted the images and gained nothing.
            product.is_scanned = True
            product.classification_reviewed_at = datetime.now(UTC)
            db.add(ProcessingQueue(
                product_id=product.id,
                task_type="ocr_text",
                priority=3,
                status="pending",
            ))
            await remove_content_type_tags(db, product.id)

        affected = len(products)
        filter_fields_updated = True
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/api/test_bulk_unflag_queues_ocr.py -q`
Expected: 4 passed

- [x] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: 592 passed, 1 failed (known)

- [x] **Step 6: Commit**

```bash
git add backend/grimoire/api/routes/bulk.py backend/tests/api/test_bulk_unflag_queues_ocr.py
git commit -m "fix(bulk): un-flagging image content now queues OCR

The un-flag branch cleared the flag, nulled product_type, deleted the
extracted images and removed content-type tags - but never queued text
extraction. So the one action meaning 'this is really a document' lost the
images without gaining the text.

Now also sets is_scanned, stamps classification_reviewed_at and enqueues
ocr_text. Fixes the Library button and the forthcoming Gallery action
together, since both go through this path."
```

---

### Task 3: "Confirm as images" endpoint

**Files:**
- Modify: `backend/grimoire/api/routes/gallery.py`
- Test: `backend/tests/api/test_gallery_review.py`

**Interfaces:**
- Consumes: `Product.classification_reviewed_at` (Task 1).
- Produces: `POST /api/v1/gallery/confirm-images` taking `{"product_ids": [int]}` and returning `{"reviewed": int}`.

⚠️ **The gallery route has no existing tests at all** (`git ls-files tests/ |
grep gallery` → nothing). Tasks 3 and 4 write the first, so no existing test
will catch a routing or response-shape mistake — these carry the whole load.
The router is mounted with `prefix="/gallery"` at
`grimoire/api/routes/__init__.py:30`, so the full path is
`/api/v1/gallery/confirm-images`.

Confirming a pack is **not** a no-op — it is what removes a correctly-classified
product from the review queue. Without it the needs-review filter never empties.

- [x] **Step 1: Write the failing test**

Create `backend/tests/api/test_gallery_review.py`:

```python
"""Confirming a product really is image content clears it from review.

Reviewing ~971 products is only tractable if the queue shrinks. Marking a scan
removes it from the gallery outright; confirming a pack has to remove it from
the *review* queue while leaving it exactly as it is.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from grimoire.database import get_db
from grimoire.main import app
from grimoire.models import Product


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def pack(db):
    product = Product(
        file_path=r"D:\Games\Fantasy Art.pdf",
        file_name="Fantasy Art.pdf",
        file_size=50_000_000,
        file_hash="aaa",
        title="Fantasy Art Subscription",
        product_type="Stock Art",
        is_image_content=True,
        images_extracted=True,
        image_count=201,
        page_count=201,
    )
    db.add(product)
    await db.commit()
    return product


@pytest.mark.asyncio
async def test_confirming_stamps_reviewed(client, db, pack):
    response = await client.post(
        "/api/v1/gallery/confirm-images", json={"product_ids": [pack.id]}
    )

    assert response.status_code == 200
    assert response.json() == {"reviewed": 1}
    assert pack.classification_reviewed_at is not None


@pytest.mark.asyncio
async def test_confirming_changes_nothing_else(client, db, pack):
    """It is a verdict, not an edit."""
    await client.post("/api/v1/gallery/confirm-images", json={"product_ids": [pack.id]})

    assert pack.is_image_content is True
    assert pack.is_scanned is False
    assert pack.product_type == "Stock Art"
    assert pack.image_count == 201
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/api/test_gallery_review.py -q`
Expected: FAIL with 404 (route does not exist), so `assert response.status_code == 200` fails

- [x] **Step 3: Add the endpoint**

Append to `backend/grimoire/api/routes/gallery.py`:

```python
class ConfirmImagesRequest(BaseModel):
    """Products the user has confirmed really are image content."""
    product_ids: list[int]


@router.post("/confirm-images")
async def confirm_images(db: DbSession, request: ConfirmImagesRequest) -> dict:
    """Record that a human judged these products correctly classified.

    Deliberately changes nothing but the timestamp. Its whole purpose is to
    remove a correctly-classified product from the needs-review queue — the
    counterpart to marking a scan, and the reason that queue can ever empty.
    """
    result = await db.execute(
        select(Product).where(Product.id.in_(request.product_ids))
    )
    products = list(result.scalars().all())

    now = datetime.now(UTC)
    for product in products:
        product.classification_reviewed_at = now

    await db.commit()
    return {"reviewed": len(products)}
```

Add to the imports at the top of the file:

```python
from datetime import datetime, UTC

from pydantic import BaseModel
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/api/test_gallery_review.py -q`
Expected: 2 passed

- [x] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: 594 passed, 1 failed (known)

- [x] **Step 6: Commit**

```bash
git add backend/grimoire/api/routes/gallery.py backend/tests/api/test_gallery_review.py
git commit -m "feat(gallery): endpoint to confirm a product really is image content

Reviewing ~971 products is only tractable if the queue shrinks, so confirming
a correctly-classified pack has to count as a verdict. Stamps
classification_reviewed_at and changes nothing else - it is a judgement, not
an edit."
```

---

### Task 4: Needs-review filter on the gallery listing

**Files:**
- Modify: `backend/grimoire/api/routes/gallery.py:13-24` and the response dict at `:109-115`
- Test: `backend/tests/api/test_gallery_review.py` (extend)

**Interfaces:**
- Consumes: `Product.classification_reviewed_at` (Task 1).
- Produces: `GET /api/v1/gallery?needs_review=true|false`, defaulting to `true`; each item gains `"classification_reviewed_at": str | None`; the response gains `"needs_review_total": int`.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/api/test_gallery_review.py`:

```python
@pytest.fixture
async def one_reviewed_one_not(db):
    from datetime import datetime, UTC

    reviewed = Product(
        file_path=r"D:\a.pdf", file_name="a.pdf", file_size=1, file_hash="a",
        title="Already Judged", is_image_content=True,
        classification_reviewed_at=datetime.now(UTC),
    )
    pending = Product(
        file_path=r"D:\b.pdf", file_name="b.pdf", file_size=1, file_hash="b",
        title="Not Yet Judged", is_image_content=True,
    )
    db.add_all([reviewed, pending])
    await db.commit()
    return reviewed, pending


@pytest.mark.asyncio
async def test_gallery_defaults_to_unreviewed_only(client, one_reviewed_one_not):
    """The backlog has to visibly shrink, so this is the default."""
    response = await client.get("/api/v1/gallery")

    titles = [i["title"] for i in response.json()["items"]]
    assert titles == ["Not Yet Judged"]


@pytest.mark.asyncio
async def test_gallery_can_show_everything(client, one_reviewed_one_not):
    response = await client.get("/api/v1/gallery", params={"needs_review": "false"})

    titles = sorted(i["title"] for i in response.json()["items"])
    assert titles == ["Already Judged", "Not Yet Judged"]


@pytest.mark.asyncio
async def test_gallery_reports_how_many_are_left(client, one_reviewed_one_not):
    response = await client.get("/api/v1/gallery", params={"needs_review": "false"})

    body = response.json()
    assert body["total"] == 2
    assert body["needs_review_total"] == 1
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/api/test_gallery_review.py -q`
Expected: 3 FAIL — the default returns both titles, and `needs_review_total` raises `KeyError`

- [x] **Step 3: Add the parameter and the condition**

In `list_gallery_products`, add a parameter after `search`:

```python
    needs_review: bool = Query(
        True,
        description="Only products no human has judged yet. On by default so the "
                    "review backlog visibly shrinks as it is worked through.",
    ),
```

After the existing `conditions = [Product.is_image_content == True]` line:

```python
    if needs_review:
        conditions.append(Product.classification_reviewed_at.is_(None))
```

- [x] **Step 4: Add the count and the per-item field**

Before the `return` at the end of the function, add:

```python
    # The GLOBAL backlog: every unreviewed image-content product, deliberately
    # ignoring tag/collection/search. It is the number being burned down, not a
    # count of what is on screen — so filtering by tag shows a count that does
    # not match the grid, and that is intended. Do not "fix" it to match the
    # filters without deciding that on purpose.
    needs_review_total = (await db.execute(
        select(func.count()).select_from(Product).where(
            Product.is_image_content == True,
            Product.classification_reviewed_at.is_(None),
        )
    )).scalar_one()
```

Add to each item dict (beside `"page_count"`):

```python
            "classification_reviewed_at": (
                p.classification_reviewed_at.isoformat()
                if p.classification_reviewed_at else None
            ),
```

Add to the returned dict:

```python
        "needs_review_total": needs_review_total,
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/api/test_gallery_review.py -q`
Expected: 5 passed

- [x] **Step 6: Run the full suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: 597 passed, 1 failed (known)

- [x] **Step 7: Commit**

```bash
git add backend/grimoire/api/routes/gallery.py backend/tests/api/test_gallery_review.py
git commit -m "feat(gallery): needs-review filter, on by default

Working through ~971 products across 40 pages of 24, the real cost is
re-covering ground. The listing now defaults to products no human has judged,
and always reports needs_review_total so remaining work is visible even with
the filter off."
```

---

### Task 5: Cover-image contribution rules

**Files:**
- Modify: `backend/grimoire/services/codex_eligibility.py`
- Modify: `backend/grimoire/services/sync_service.py:624` (inside `queue_product_for_contribution`)
- Test: `backend/tests/services/test_cover_sharing.py`

**Interfaces:**
- Consumes: `Product.is_scanned` (Task 1); existing `is_codex_eligible(product) -> tuple[bool, str]`.
- Produces: `may_share_cover(product: Product) -> bool` in `codex_eligibility.py`.

- [x] **Step 1: Write the failing test**

Create `backend/tests/services/test_cover_sharing.py`:

```python
"""Metadata is factual and contributable; artwork is the publisher's.

Grimoire sends `cover_image_base64` on every contribution. Many scanned books
came from third parties years ago and their provenance cannot be established,
and for anything Codex already has a cover for, sending one adds nothing.

Two rules covering different halves. "Codex already has one" keys on the
match, so it cannot help for a new_product — where Codex knows nothing and a
scan's cover would otherwise be the first uploaded. Neither rule blocks the
contribution; both drop only the image.
"""
import pytest

from grimoire.models import Product, Setting
from grimoire.services import sync_service
from grimoire.services.codex import (
    CodexMatch, CodexProduct, IdentificationSource, MatchType,
)
from grimoire.services.codex_eligibility import may_share_cover


def _product(**kw):
    base = dict(
        file_path=r"D:\Games\thing.pdf", file_name="thing.pdf", file_size=1024,
        file_hash="h", title="A Thing", cover_extracted=True,
        cover_image_path=r"D:\covers\1.jpg",
    )
    base.update(kw)
    return Product(**base)


def test_a_scanned_product_may_not_share_its_cover():
    assert may_share_cover(_product(is_scanned=True)) is False


def test_an_ordinary_product_may():
    assert may_share_cover(_product(is_scanned=False)) is True


class _Client:
    def __init__(self, cover_url=None, match=True):
        self._cover_url = cover_url
        self._match = match

    async def is_available(self):
        return True

    async def identify_by_hash(self, file_hash):
        if not self._match:
            return None
        return CodexMatch(
            match_type=MatchType.EXACT, confidence=1.0,
            product=CodexProduct(id="x", title="A Thing", cover_url=self._cover_url),
            source=IdentificationSource.CODEX_HASH,
        )

    async def identify_by_title(self, title, filename=None):
        return await self.identify_by_hash(None)


async def _queue(db, product, client, monkeypatch):
    """Queue a contribution and return the payload that was stored.

    ⚠️ `get_cover_image_base64` reads a real file and returns None when it is
    missing, so without stubbing it every assertion below would pass whether
    or not the rules work. It is imported *inside* `build_contribution_data`,
    so the patch has to target `contribution_service`, where it is looked up
    at call time.
    """
    import json

    from sqlalchemy import select

    from grimoire.models import ContributionQueue
    from grimoire.services import contribution_service

    monkeypatch.setattr(
        contribution_service, "get_cover_image_base64", lambda product: "BASE64DATA"
    )
    monkeypatch.setattr(sync_service, "get_codex_client", lambda **kw: client)

    db.add(Setting(key="codex_api_key", value='"test-key"'))
    db.add(product)
    await db.commit()

    await sync_service.queue_product_for_contribution(
        db=db, product=product, submit_immediately=False, skip_no_change_check=True
    )
    row = (await db.execute(select(ContributionQueue))).scalars().one()
    return json.loads(row.contribution_data)


@pytest.mark.asyncio
async def test_an_ordinary_product_still_sends_its_cover(db, monkeypatch):
    """The control. Without it the three assertions below prove nothing."""
    payload = await _queue(db, _product(), _Client(cover_url=None), monkeypatch)

    assert payload["cover_image_base64"] == "BASE64DATA"


@pytest.mark.asyncio
async def test_no_cover_is_sent_when_codex_already_has_one(db, monkeypatch):
    payload = await _queue(
        db, _product(), _Client(cover_url="https://images/x.jpg"), monkeypatch
    )

    assert "cover_image_base64" not in payload


@pytest.mark.asyncio
async def test_no_cover_is_sent_for_a_scan_codex_does_not_know(db, monkeypatch):
    """The new_product case the first rule cannot reach."""
    payload = await _queue(db, _product(is_scanned=True), _Client(match=False), monkeypatch)

    assert "cover_image_base64" not in payload


@pytest.mark.asyncio
async def test_a_local_edit_also_withholds_a_scan_cover(db, monkeypatch):
    """The second build site. Missed by the first draft of this plan: editing a
    scanned product locally and syncing the edit would still have uploaded the
    cover, with no test covering that path."""
    import json

    from sqlalchemy import select

    from grimoire.models import ContributionQueue
    from grimoire.services import contribution_service

    monkeypatch.setattr(
        contribution_service, "get_cover_image_base64", lambda product: "BASE64DATA"
    )
    monkeypatch.setattr(sync_service, "get_codex_client", lambda **kw: _Client(match=False))

    product = _product(is_scanned=True)
    db.add(Setting(key="codex_api_key", value='"test-key"'))
    db.add(product)
    await db.commit()

    await sync_service.queue_local_edit_for_sync(
        db=db, product=product, edited_fields={"publisher": "Fixed By Hand"}
    )

    row = (await db.execute(select(ContributionQueue))).scalars().one()
    payload = json.loads(row.contribution_data)
    assert payload["publisher"] == "Fixed By Hand"
    assert "cover_image_base64" not in payload


@pytest.mark.asyncio
async def test_a_scan_costs_no_lookup(db, monkeypatch):
    """`may_share_cover` short-circuits: no answer from Codex would change the
    result, so a scan must not spend a round trip asking."""
    from grimoire.services.sync_service import resolve_include_cover

    class _Explodes:
        async def identify_by_hash(self, file_hash):
            raise AssertionError("a scan must not cost an /identify call")

    assert await resolve_include_cover(_product(is_scanned=True), _Explodes()) is False
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/services/test_cover_sharing.py -q`
Expected: FAIL with `ImportError: cannot import name 'may_share_cover'`

- [x] **Step 3: Add the predicate**

Append to `backend/grimoire/services/codex_eligibility.py`:

```python
def may_share_cover(product: Product) -> bool:
    """Whether this product's cover image may be uploaded to Codex.

    Separate from `is_codex_eligible`, which governs whether the product may
    be contributed at all. A scanned book is perfectly contributable — its
    title, publisher and year are facts about a published work — but its cover
    is the publisher's artwork, and for scans of uncertain provenance that is
    the part not to republish.
    """
    return not product.is_scanned
```

- [x] **Step 4: Add a shared helper that resolves the cover decision once**

⚠️ **Amended after adversarial review (finding 3).** The first draft called
`identify_by_hash` here unconditionally. On the default path
(`skip_no_change_check=False`) `should_contribute` has *already* made that call
and thrown the result away, so every contribution would cost two `/identify`
round trips where one suffices. Phase 0 established that throttling is real.

Add to `backend/grimoire/services/sync_service.py`, above
`queue_product_for_contribution`:

```python
async def resolve_include_cover(
    product: Product,
    client: CodexClient,
    match: "CodexMatch | None" = None,
    match_known: bool = False,
) -> bool:
    """Whether this contribution should carry a cover image.

    Two independent rules. `may_share_cover` keys on the product; the second
    keys on Codex already having one, which cannot help for a new_product —
    exactly where a scan's cover would be the first uploaded.

    Pass `match_known=True` with an already-fetched `match` to reuse a lookup
    the caller has made; otherwise this makes one. A scan short-circuits before
    any lookup at all, since no answer would change the result.
    """
    if not may_share_cover(product):
        return False

    if not match_known:
        try:
            match = await client.identify_by_hash(product.file_hash)
        except CodexLookupError:
            # Could not ask. Withhold rather than guess — a cover not sent
            # costs nothing, and one sent cannot be recalled.
            return False

    return not (match and match.product and match.product.cover_url)
```

Add `CodexMatch` to the existing `from grimoire.services.codex import (...)`
block, and `may_share_cover` to the eligibility import:

```python
from grimoire.services.codex_eligibility import is_codex_eligible, may_share_cover
```

- [x] **Step 5: Let `should_contribute` hand back the match it already fetched**

Change its signature so a caller can both supply and receive the lookup.
Backward compatible — existing callers and tests pass nothing:

```python
async def should_contribute(
    product: Product,
    codex_client: CodexClient,
    on_match=None,
) -> tuple[bool, str]:
```

Immediately after the successful `identify_by_hash` call inside it, add:

```python
    if on_match is not None:
        on_match(match)
```

- [x] **Step 6: Apply at both build sites**

⚠️ **Amended after adversarial review (finding 1).** The first draft patched
only `queue_product_for_contribution`. `queue_local_edit_for_sync` builds a
payload too, so a locally-edited scan would still have uploaded its cover —
a spec acceptance criterion silently unmet, with no test to catch it.

In `queue_product_for_contribution`, capture the match from the eligibility
check. Replace the `if not skip_no_change_check:` block's inner lines so the
match is recorded:

```python
    seen_match = None
    match_known = False

    if not skip_no_change_check:
        codex = get_codex_client()
        if await codex.is_available():
            def _capture(m):
                nonlocal seen_match, match_known
                seen_match, match_known = m, True

            should, reason = await should_contribute(product, codex, on_match=_capture)
            if not should:
                logger.debug(f"Skipping contribution for product {product.id}: {reason}")
                return {
                    "success": False,
                    "reason": "no_new_data",
                    "message": "Product already has complete data in Codex",
                }
```

Then replace `contribution_data = build_contribution_data(product)` (`:624`) with:

```python
    include_cover = await resolve_include_cover(
        product, get_codex_client(api_key=api_key), seen_match, match_known
    )
    contribution_data = build_contribution_data(product, include_cover=include_cover)
```

And in `queue_local_edit_for_sync`, replace its
`contribution_data = build_contribution_data(product)` (`:736`) with:

```python
    include_cover = await resolve_include_cover(
        product, get_codex_client(api_key=api_key)
    )
    contribution_data = build_contribution_data(product, include_cover=include_cover)
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/services/test_cover_sharing.py -q`
Expected: 5 passed

- [x] **Step 6: Run the full suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: 601 passed, 1 failed (known)

- [x] **Step 7: Commit**

```bash
git add backend/grimoire/services/codex_eligibility.py backend/grimoire/services/sync_service.py backend/tests/services/test_cover_sharing.py
git commit -m "feat(codex): stop uploading cover art we should not

Grimoire sent cover_image_base64 on every contribution. Two independent rules
now drop it: never send a cover Codex already has, and never send a scanned
product's cover.

The second is not redundant. The first keys on the match, so for a
new_product - where Codex knows nothing - a scan's cover would otherwise be
the first one uploaded, which is the case of concern. A failed lookup also
withholds: a cover not sent costs nothing, one sent cannot be recalled.

Metadata still contributes in full; only the image is dropped."
```

---

### Task 6: Gallery multi-select and review actions

**Files:**
- Modify: `frontend/src/api/gallery.ts`
- Modify: `frontend/src/pages/Gallery.tsx`

**Interfaces:**
- Consumes: `POST /api/v1/gallery/confirm-images` (Task 3), `GET /api/v1/gallery?needs_review=` and `needs_review_total` (Task 4), `POST /api/v1/bulk/update` with `{product_ids, is_image_content: false}` (Task 2).
- Produces: nothing consumed by later tasks.

- [x] **Step 1: Extend the API client**

In `frontend/src/api/gallery.ts`, add to `GalleryProduct`:

```typescript
  classification_reviewed_at: string | null;
```

Add to `GalleryResponse`:

```typescript
  needs_review_total: number;
```

Add to `GalleryFilters` (`gallery.ts:32`):

```typescript
  needs_review?: boolean;
```

⚠️ **Amended after adversarial review (finding 2). Adding the interface field
is not enough, and getting this wrong fails silently.** `getGalleryProducts`
(`gallery.ts:58`) builds its query string key by key, so an unlisted field is
simply never sent — the checkbox would appear to work and change nothing, with
`tsc` reporting no error. The obvious guard is also wrong: `if
(filters.needs_review)` is falsy for `false`, which is the one value that has
to be transmitted. Add to `getGalleryProducts`, beside the `search` line:

```typescript
  if (filters.needs_review !== undefined) {
    params.set('needs_review', String(filters.needs_review));
  }
```

Add two functions:

```typescript
export async function markAsScans(productIds: number[]): Promise<void> {
  await client.post('/bulk/update', {
    product_ids: productIds,
    is_image_content: false,
  });
}

export async function confirmAsImages(productIds: number[]): Promise<{ reviewed: number }> {
  const res = await client.post('/gallery/confirm-images', { product_ids: productIds });
  return res.data;
}
```

- [x] **Step 2: Add selection state and the action bar**

In `frontend/src/pages/Gallery.tsx`, add beside the existing `useState` calls:

```typescript
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const toggle = (id: number) =>
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const reviewMutation = useMutation({
    mutationFn: async (action: 'scans' | 'images') => {
      const ids = [...selected];
      if (action === 'scans') await markAsScans(ids);
      else await confirmAsImages(ids);
    },
    onSuccess: () => {
      setSelected(new Set());
      queryClient.invalidateQueries({ queryKey: ['gallery'] });
    },
  });
```

Render above the grid, only when something is selected:

```tsx
      {selected.size > 0 && (
        <div
          className="sticky top-0 z-10 mb-4 flex items-center gap-3 rounded-lg border p-3"
          style={{
            borderColor: 'var(--color-border)',
            backgroundColor: 'var(--color-surface-raised)',
          }}
        >
          <span style={{ color: 'var(--color-text-primary)' }}>
            {selected.size} selected
          </span>
          <button
            onClick={() => reviewMutation.mutate('scans')}
            disabled={reviewMutation.isPending}
            className="rounded px-3 py-1.5 text-sm"
            style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
          >
            Mark as scans
          </button>
          <button
            onClick={() => reviewMutation.mutate('images')}
            disabled={reviewMutation.isPending}
            className="rounded border px-3 py-1.5 text-sm"
            style={{
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          >
            Confirm as images
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="ml-auto text-sm"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            Clear
          </button>
        </div>
      )}
```

Import `useMutation` and `useQueryClient` from `@tanstack/react-query` if not
already imported, and `markAsScans`/`confirmAsImages` from `../api/gallery`.
Add `const queryClient = useQueryClient();` beside the other hooks.

- [x] **Step 3: Add the checkbox and the pages/images hint to the card**

Change the `GalleryCard` signature and body. The outer element must become a
`div` — a checkbox inside a `<button>` is invalid HTML and swallows the click:

```tsx
function GalleryCard({
  product, onClick, selected, onToggle,
}: {
  product: GalleryProduct;
  onClick: () => void;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className="group relative overflow-hidden rounded-lg border text-left transition-shadow hover:shadow-lg"
      style={{
        borderColor: selected ? 'var(--color-accent)' : 'var(--color-border)',
        backgroundColor: 'var(--color-surface)',
      }}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        aria-label={`Select ${product.title}`}
        className="absolute left-2 top-2 z-10 h-4 w-4 cursor-pointer"
      />
      <button onClick={onClick} className="w-full text-left">
        {/* existing cover <div className="aspect-[3/4] ..."> block unchanged */}
        <div className="p-2">
          <p className="truncate text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
            {product.title}
          </p>
          <div className="mt-1 flex items-center gap-1">
            {product.tags.slice(0, 2).map(tag => (
              <span
                key={tag.id}
                className="rounded px-1.5 py-0.5 text-xs text-white"
                style={{ backgroundColor: tag.color || '#888' }}
              >
                {tag.name}
              </span>
            ))}
            {/* The strongest visual tell: one image per page means a scan,
                which is what separates a 36pg module from an 864pg card deck. */}
            {product.image_count > 0 && (
              <span
                className="ml-auto text-xs"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                {product.page_count ?? '?'}pg / {product.image_count}img
              </span>
            )}
          </div>
        </div>
      </button>
    </div>
  );
}
```

Update the call site in the grid to pass the new props:

```tsx
                <GalleryCard
                  key={product.id}
                  product={product}
                  onClick={() => setExpandedProduct(product)}
                  selected={selected.has(product.id)}
                  onToggle={() => toggle(product.id)}
                />
```

- [x] **Step 4: Add the needs-review toggle**

Beside the existing tag/collection filter buttons:

```tsx
        <label
          className="flex items-center gap-2 text-sm"
          style={{ color: 'var(--color-text-primary)' }}
        >
          <input
            type="checkbox"
            checked={filters.needs_review !== false}
            onChange={e =>
              setFilters(prev => ({
                ...prev,
                needs_review: e.target.checked ? undefined : false,
                page: 1,
              }))
            }
          />
          Needs review{gallery ? ` (${gallery.needs_review_total})` : ''}
        </label>
```

⚠️ **Amended after adversarial review (finding 4).** The query result is
destructured as `const { data: gallery, isLoading }` (`Gallery.tsx:15`), so it
is `gallery`, not `data`. This one fails `tsc -b` loudly rather than silently,
but it is still wrong.

The query key is `['gallery', filters]`, so `invalidateQueries({ queryKey:
['gallery'] })` in the mutation matches it by prefix.

- [x] **Step 5: Typecheck**

Run: `cd frontend && npx tsc -b`
Expected: no errors

- [x] **Step 6: Commit**

```bash
git add frontend/src/api/gallery.ts frontend/src/pages/Gallery.tsx
git commit -m "feat(gallery): multi-select review with scan/image actions

Checkbox per card, sticky action bar, and a needs-review filter on by default
so the ~971-product backlog visibly shrinks. Cards show pages/images, which is
the strongest visual tell - one image per page means a scan, and it is what
separates a 36-page module from an 864-page card deck at a glance.

GalleryCard's outer element becomes a div: a checkbox inside a button is
invalid HTML and swallows the click."
```

---

### Task 7: Manual end-to-end verification

**Files:** none — this task is a check, not a change.

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

The five products the user reported are the acceptance test. There is no
automated coverage for "OCR actually ran against the real library", and the
frontend has no test harness, so this step is where those claims get earned.

- [x] **Step 1: Start the app**

Run `start.bat` from the repo root, in an interactive terminal.
⚠️ `start.bat` ends in `pause`; it cannot be launched headlessly — run where
stdin is a real console, or it exits immediately and kills what it started.

- [x] **Step 2: Confirm the backlog count**

Open the Gallery. The "Needs review" checkbox should be checked, and its count
should read close to 1,710 (every flagged product starts unreviewed).

- [x] **Step 3: Mark the reported products as scans**

Search for `Volturnus`. Select *SF1 Volturnus Planet of Mystery*, *SFKH4 The War
Machine*, *SF4 Mision to Alcazzar*, then search for and select *Children of the
Night - Werebeasts* and *On Hallowed Ground*. Click **Mark as scans**.

Expected: they disappear from the grid, and the needs-review count falls by five.

- [x] **Step 4: Confirm OCR runs**

The queue worker must be unpaused ("Grimoire Working"). Wait for the five
`ocr_text` tasks to complete — *On Hallowed Ground* is 195 pages and will take
several minutes.

Verify with:

```bash
cd backend && python -c "
import sqlite3
c = sqlite3.connect('file:data/grimoire.db?mode=ro', uri=True)
for r in c.execute('''select title, is_scanned, is_image_content, text_extracted,
                             text_unextractable
                      from products where title like '%Volturnus%'
                         or title like '%Hallowed Ground%' '''):
    print(r)
"
```

Expected: `is_scanned=1`, `is_image_content=0`, `text_extracted=1`,
`text_unextractable=0`.

- [x] **Step 5: Confirm the text is searchable**

Search the Library for `Kurabanda` (a creature named on page 6 of SF1 Volturnus,
confirmed present by OCR during the spec work). Expected: SF1 Volturnus is a hit.

- [x] **Step 6: Confirm a pack stays a pack**

Find *Fantasy Art Subscription* in the Gallery, select it, click **Confirm as
images**. Expected: it leaves the needs-review grid; unchecking "Needs review"
shows it still present, still image content, still with its images.

- [x] **Step 7: Record the outcome**

Report which of steps 2–6 passed. If OCR returned nothing for any product, note
whether it was marked `text_unextractable` — that is the designed safety net and
means the system behaved correctly on a bad call, not that the task failed.


### Outcome (2026-08-25)

Steps 2-6 all passed against the live library.

- **Step 2** - backlog read 1,711, matching the plan's estimate.
- **Step 3** - the five reported products were marked as scans and left the
  grid. The run was carried well past them: **107 products** rescued in total,
  backlog down to 1,463.
- **Step 4** - OCR ran on all 107 and every one produced text. Quality is real,
  not just present: SF1 Volturnus yielded 55,684 words at a 31% common-word
  ratio. None were marked `text_unextractable`; the 5 failed `ocr_text` tasks
  were pre-existing and unrelated (4 oversized-guard rejections over 250 MB,
  1 genuinely blank handout).
- **Step 5** - **failed first, and uncovered a separate long-standing bug.**
  The OCR'd text was not searchable: `products_fts_update` rewrote the row with
  a six-column INSERT into a seven-column table, blanking
  `products_fts.extracted_text` on *every* product UPDATE.
  `update_search_vector` tripped it itself by setting `deep_indexed = True`
  immediately after writing the body, so it could not index a book even once.
  All 15 finished scans were affected, plus ~13% of the whole library (2,800
  products) - this predates the scan work entirely. Fixed in `dc377a7`; the
  trigger now updates only the metadata columns it owns. All 2,800 were
  re-indexed with zero failures, leaving 3 products with genuinely empty text
  (two zero-char maps, one missing file). `extracted_text:Kurabanda` now
  matches SF1 Volturnus, the exact query that failed.
- **Step 6** - packs stayed packs. *CR1 Wizard Spell Cards* (854pg) is still
  image content, as are the map and card-deck products. Zero products carry
  both `is_scanned` and `is_image_content`.

**Known limitation, not a defect of this work.** `update_search_vector`
truncates the indexed body at 50,000 characters (`fts_service.py:113`), so only
the first ~30% of a large scan is searchable - *SF4 Mision to Alcazzar* indexes
50,000 of its 117,897 characters. Worth its own spec.

**Booby trap found nearby.** `POST /queue/fts/recreate` is the obvious-looking
repair endpoint, but it recreates `products_fts` with a six-column schema that
omits `description`, which would corrupt the index and wipe every indexed body.
The backfill used `POST /queue/fts/rebuild-all` instead. Left unfixed.

---

## Notes for the implementer

**What this plan deliberately does not do.** The classifier
(`image_classifier.py:205`) is left broken: it flags any PDF with no text layer
as image content, which is why scanned books land in the Gallery. An earlier
design probed pages with OCR and decided automatically; it was measured against
15 hand-labelled products and rejected, because a real scan (*Planes of Chaos*,
175 median words/page) scored below a real card deck (*CR1 Wizard Spell Cards*,
176). New scans will keep being misclassified, and will keep appearing in the
Gallery for review. This is recorded in the spec, not an oversight.

**Order matters between Tasks 2 and 6.** The Gallery's "Mark as scans" button
calls the bulk endpoint fixed in Task 2. Building the UI first gives you a
button that deletes images and produces no text — the exact bug being fixed.

**`skip_no_change_check=True` in Task 5's tests** is deliberate: it bypasses
`should_contribute`, which is how the test reaches the cover logic without
needing a full eligibility round trip. It also exercises the path a real sync
uses.
