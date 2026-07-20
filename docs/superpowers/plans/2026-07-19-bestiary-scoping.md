# Bestiary Scoping and Review Throughput Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This project's owner has asked that this plan be executed INLINE (superpowers:executing-plans), not with subagents.** Subagent dispatch burns their weekly limit and needs specific justification.

**Goal:** Make the bestiary usable at scale — confirm entries in bulk, scope results to chosen books, save queries as favorites, refuse extractions that cannot work, and queue an extraction from the book detail modal.

**Architecture:** Five additions to the existing bestiary feature. Four are backend-first (bulk status endpoint, multi-book filter + `/books`, a `BestiaryFavorite` table with CRUD, a dry-run guard in the extract route), each with pytest coverage; two are frontend (Bestiary page controls, product modal action) gated by `tsc -b`. No new dependencies.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, SQLite/aiosqlite, pytest (+asyncio auto mode), React 18 + TypeScript, React Query v5, axios.

**Spec:** `docs/superpowers/specs/2026-07-19-bestiary-scoping-design.md` — read it before starting.

## Global Constraints

- Work on branch `feat/bestiary-scoping` off `main`.
- Backend tests run from `backend/` with miniconda: `python -m pytest` (NOT `.venv` — it lacks pytest). Baseline is **323 passed, 6 failed**; those 6 are pre-existing (`test_diagnostics` ×2, `test_products_list` ×1, `test_scanner_batch` ×1, `test_backup_routes` ×2). Only new failures matter.
- Frontend gate is `npx tsc -b` from `frontend/` (no frontend test harness). One known pre-existing error: `src/pages/Settings.tsx(3,137): error TS6133: 'Shield' is declared but its value is never read.` Use `npx tsc -b --force` for a clean re-check; `tsc -b` is incremental and may report nothing on a repeat run.
- A `UserWarning: Using auto-generated SECRET_KEY` appears on every test file. Pre-existing, accepted for this local-only app. Not a finding.
- Route handlers commit explicitly — `get_db()` does NOT auto-commit.
- JSON-in-Text columns follow the `ProcessingQueue.config` convention: `json.dumps` to store, `json.loads` to read.
- Only `review_status == "confirmed"` entries feed browse/random/metrics. `POST /random` stays confirmed-only and must not be overridable by the request body.
- New tables are created by `Base.metadata.create_all` in `init_db()` and the test fixtures — no `_ensure_columns()` entry (that mechanism is only for new COLUMNS on EXISTING tables).
- SQLAlchemy `default=` is DDL-level; the Python constructor gives `None` for unset fields.
- The test `db` fixture rolls back uncommitted work, but the engine is session-scoped — committed rows persist across tests in the same run. Use distinct file paths/names per test.
- Route functions are called directly in tests with the `db` fixture and explicit keyword args (no HTTP client). Keep signatures compatible with direct invocation.
- Declare literal paths (`/books`, `/favorites`, `/bulk-status`) BEFORE `/{entry_id}`-shaped routes, or the parameterized route captures them.
- Tool output carries name/page/book pointers, short derived tags, and computed math — never stat-block prose. (`raw_text` in review mode and `special_abilities` in browse are the two settled exceptions.)

## File Structure

| File | Responsibility |
|---|---|
| `backend/grimoire/api/routes/monsters.py` (modify) | All five backend endpoints live here; it is the bestiary API surface |
| `backend/grimoire/models/bestiary_favorite.py` (create) | `BestiaryFavorite` ORM model |
| `backend/grimoire/models/__init__.py` (modify) | Register the model |
| `backend/grimoire/services/queue_processor.py` (modify) | Handler raises `TaskError` on zero candidates |
| `backend/tests/test_monsters_bulk.py` (create) | Bulk status endpoint |
| `backend/tests/test_monsters_books.py` (create) | `product_ids` filter + `/books` |
| `backend/tests/test_monsters_favorites.py` (create) | Favorites CRUD |
| `backend/tests/test_monsters_guard.py` (create) | Extraction guard + handler zero-candidate failure |
| `frontend/src/api/monsters.ts` (modify) | Client for all new/changed endpoints |
| `frontend/src/components/MultiCombobox.tsx` (create) | Searchable multi-select over `{id, label, count}` options |
| `frontend/src/pages/Bestiary.tsx` (modify) | Bulk selection, book filter, favorites UI |
| `frontend/src/components/ProductDetail.tsx` (modify) | "Extract as bestiary" action |

`MultiCombobox` is a **sibling** of the existing `ComboboxWithAdd.tsx`, not a generalisation of it. Multi-select changes the value type, the trigger rendering, whether the popup closes on pick, and removes the add-new path — that is most of the component. `ComboboxWithAdd` is already used by `ProductDetail`, so threading a `multi` flag through it risks a regression there for little gain.

New tests go in their own files rather than growing `test_monsters_api.py` (already 14 tests), keeping each file to one concern.

---

### Task 1: Bulk review status endpoint

**Files:**
- Modify: `backend/grimoire/api/routes/monsters.py`
- Test: `backend/tests/test_monsters_bulk.py` (create)

**Interfaces:**
- Consumes: `MonsterEntry`, `DbSession`, `VALID_STATUSES` (already defined in `monsters.py`)
- Produces: `class BulkStatusRequest(BaseModel)` with `ids: list[int]`, `review_status: str`; `async bulk_status(db, request) -> dict` returning `{"updated": int}`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_monsters_bulk.py
"""Tests for bulk review-status updates."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from grimoire.api.routes.monsters import BulkStatusRequest, bulk_status
from grimoire.models import MonsterEntry, Product


async def seed_entries(db, path, names, status="pending"):
    product = Product(
        file_path=path, file_name=path.rsplit("/", 1)[-1],
        file_size=1, file_hash=path, title="Bulk Test Book",
    )
    db.add(product)
    await db.flush()
    entries = []
    for name in names:
        entry = MonsterEntry(
            product_id=product.id, name=name, page_number=1, system_profile="dcc",
            raw_text="raw", ac=12, hd_dice="1d8", hd_value=1.0, hp_avg=4.5,
            attacks=json.dumps([]), environments=json.dumps([]),
            special_abilities=json.dumps([]), flags=json.dumps([]),
            review_status=status,
        )
        db.add(entry)
        entries.append(entry)
    await db.flush()
    return product, entries


async def test_bulk_confirm_updates_all_given_ids(db):
    _, entries = await seed_entries(db, "/t/bulk-confirm.pdf", ["Bulk Orc", "Bulk Rat", "Bulk Bat"])
    ids = [e.id for e in entries]

    result = await bulk_status(db=db, request=BulkStatusRequest(ids=ids, review_status="confirmed"))
    assert result["updated"] == 3

    rows = (await db.execute(select(MonsterEntry).where(MonsterEntry.id.in_(ids)))).scalars().all()
    assert {r.review_status for r in rows} == {"confirmed"}


async def test_bulk_leaves_unlisted_entries_alone(db):
    _, entries = await seed_entries(db, "/t/bulk-partial.pdf", ["Keep Me", "Change Me"])
    keep, change = entries

    result = await bulk_status(db=db, request=BulkStatusRequest(ids=[change.id], review_status="rejected"))
    assert result["updated"] == 1

    await db.refresh(keep)
    await db.refresh(change)
    assert keep.review_status == "pending"
    assert change.review_status == "rejected"


async def test_bulk_rejects_invalid_status(db):
    _, entries = await seed_entries(db, "/t/bulk-badstatus.pdf", ["Bad Status Orc"])
    with pytest.raises(HTTPException) as exc:
        await bulk_status(db=db, request=BulkStatusRequest(ids=[entries[0].id], review_status="maybe"))
    assert exc.value.status_code == 422


async def test_bulk_empty_ids_is_a_noop(db):
    result = await bulk_status(db=db, request=BulkStatusRequest(ids=[], review_status="confirmed"))
    assert result["updated"] == 0


async def test_bulk_unknown_ids_are_skipped(db):
    _, entries = await seed_entries(db, "/t/bulk-unknown.pdf", ["Real Orc"])
    result = await bulk_status(
        db=db, request=BulkStatusRequest(ids=[entries[0].id, 99999999], review_status="confirmed")
    )
    # Only the row that exists is counted, so a caller can detect a mismatch.
    assert result["updated"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/`: `python -m pytest tests/test_monsters_bulk.py -v`
Expected: FAIL with `ImportError: cannot import name 'BulkStatusRequest'`

- [ ] **Step 3: Write the implementation**

In `backend/grimoire/api/routes/monsters.py`, add this request model after the existing `RandomRequest` class:

```python
class BulkStatusRequest(BaseModel):
    ids: list[int]
    review_status: str
```

Then add this route. It MUST be declared before the `@router.patch("/{entry_id}")` route so the literal path is not captured by the parameterized one:

```python
@router.post("/bulk-status")
async def bulk_status(db: DbSession, request: BulkStatusRequest) -> dict:
    """Set review_status on many entries in one transaction.

    One UPDATE and one commit, rather than one request per entry: confirming
    175 entries via PATCH took over five minutes because each request forced
    its own fsync against a large database.
    """
    if request.review_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"review_status must be one of {sorted(VALID_STATUSES)}"
        )
    if not request.ids:
        return {"updated": 0}

    result = await db.execute(
        update(MonsterEntry)
        .where(MonsterEntry.id.in_(request.ids))
        .values(review_status=request.review_status)
    )
    await db.commit()
    # rowcount reflects rows that actually existed, so unknown ids are skipped
    # silently but visibly — the caller can compare against len(ids).
    return {"updated": result.rowcount or 0}
```

Add `update` to the existing SQLAlchemy import line at the top of the file, so it reads:

```python
from sqlalchemy import func, select, update
```

- [ ] **Step 4: Run tests to verify they pass**

From `backend/`: `python -m pytest tests/test_monsters_bulk.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/api/routes/monsters.py backend/tests/test_monsters_bulk.py
git commit -m "feat(bestiary): bulk review-status endpoint"
```

---

### Task 2: Multi-book filter and books listing

**Files:**
- Modify: `backend/grimoire/api/routes/monsters.py`
- Test: `backend/tests/test_monsters_books.py` (create)

**Interfaces:**
- Consumes: `MonsterEntry`, `Product`, `_base_conditions`, `_entry_to_dict`
- Produces: `_base_conditions(..., product_ids: list[int] | None, ...)` replacing the `product_id` parameter; `list_monsters(..., product_ids: list[int] | None = Query(None), ...)`; `RandomRequest.product_ids: list[int] | None`; `async list_books(db, review_status: str = "confirmed") -> dict` returning `{"books": [{"product_id": int, "title": str | None, "count": int}]}`

This is a breaking change to `product_id` on the list and random endpoints. `POST /monsters/extract/{product_id}` keeps its path parameter — it acts on one book by definition.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_monsters_books.py
"""Tests for multi-book filtering and the books listing."""

import json

from grimoire.api.routes.monsters import RandomRequest, list_books, list_monsters, random_monsters
from grimoire.models import MonsterEntry, Product


async def seed_book(db, path, title, names, status="confirmed"):
    product = Product(
        file_path=path, file_name=path.rsplit("/", 1)[-1],
        file_size=1, file_hash=path, title=title,
    )
    db.add(product)
    await db.flush()
    for name in names:
        db.add(MonsterEntry(
            product_id=product.id, name=name, page_number=1, system_profile="dcc",
            raw_text="raw", ac=12, hd_dice="1d8", hd_value=1.0, hp_avg=4.5,
            attacks=json.dumps([]), environments=json.dumps(["books-test-env"]),
            special_abilities=json.dumps([]), flags=json.dumps([]),
            review_status=status,
        ))
    await db.flush()
    return product


async def test_product_ids_filters_to_selected_books(db):
    book_a = await seed_book(db, "/t/books-a.pdf", "Book A", ["Aardvark A", "Badger A"])
    await seed_book(db, "/t/books-b.pdf", "Book B", ["Cougar B"])

    result = await list_monsters(db=db, product_ids=[book_a.id], environment="books-test-env")
    names = sorted(i["name"] for i in result["items"])
    assert names == ["Aardvark A", "Badger A"]


async def test_product_ids_accepts_multiple_books(db):
    book_a = await seed_book(db, "/t/books-multi-a.pdf", "Multi A", ["Multi Ant"])
    book_b = await seed_book(db, "/t/books-multi-b.pdf", "Multi B", ["Multi Bee"])

    result = await list_monsters(
        db=db, product_ids=[book_a.id, book_b.id], environment="books-test-env"
    )
    assert sorted(i["name"] for i in result["items"]) == ["Multi Ant", "Multi Bee"]


async def test_empty_product_ids_means_all_books(db):
    await seed_book(db, "/t/books-all-a.pdf", "All A", ["All Aurochs"])
    await seed_book(db, "/t/books-all-b.pdf", "All B", ["All Bison"])

    result = await list_monsters(db=db, environment="books-test-env")
    names = [i["name"] for i in result["items"]]
    assert "All Aurochs" in names
    assert "All Bison" in names


async def test_random_respects_product_ids(db):
    book_a = await seed_book(db, "/t/books-rand-a.pdf", "Rand A", ["Rand Auk"])
    await seed_book(db, "/t/books-rand-b.pdf", "Rand B", ["Rand Boar"])

    result = await random_monsters(
        db=db, request=RandomRequest(count=10, product_ids=[book_a.id], environment="books-test-env")
    )
    names = [i["name"] for i in result["items"]]
    assert "Rand Auk" in names
    assert "Rand Boar" not in names


async def test_list_books_counts_confirmed_by_default(db):
    book = await seed_book(db, "/t/books-count.pdf", "Counted Book", ["Count One", "Count Two"])
    await seed_book(db, "/t/books-count-pending.pdf", "Pending Book", ["Hidden One"], status="pending")

    result = await list_books(db=db)
    by_id = {b["product_id"]: b for b in result["books"]}
    assert by_id[book.id]["title"] == "Counted Book"
    assert by_id[book.id]["count"] == 2
    # A book with only pending entries must not appear in the confirmed listing.
    assert all(b["title"] != "Pending Book" for b in result["books"])


async def test_list_books_honors_review_status(db):
    """Review mode needs books whose entries are all still pending."""
    await seed_book(db, "/t/books-review.pdf", "Review Book", ["Review One"], status="pending")

    result = await list_books(db=db, review_status="pending")
    assert any(b["title"] == "Review Book" and b["count"] == 1 for b in result["books"])
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/`: `python -m pytest tests/test_monsters_books.py -v`
Expected: FAIL with `ImportError: cannot import name 'list_books'`

- [ ] **Step 3: Change `_base_conditions` to take `product_ids`**

In `backend/grimoire/api/routes/monsters.py`, replace the `product_id` parameter and its condition:

```python
def _base_conditions(
    environment: str | None = None,
    system_profile: str | None = None,
    product_ids: list[int] | None = None,
    review_status: str | None = "confirmed",
    hd_min: float | None = None,
    hd_max: float | None = None,
    q: str | None = None,
) -> list:
    conditions = []
    if review_status:
        conditions.append(MonsterEntry.review_status == review_status)
    if environment:
        conditions.append(MonsterEntry.environments.like(f'%"{environment}"%'))
    if system_profile:
        conditions.append(MonsterEntry.system_profile == system_profile)
    if product_ids:
        conditions.append(MonsterEntry.product_id.in_(product_ids))
    if hd_min is not None:
        conditions.append(MonsterEntry.hd_value >= hd_min)
    if hd_max is not None:
        conditions.append(MonsterEntry.hd_value <= hd_max)
    if q:
        conditions.append(MonsterEntry.name.ilike(f"%{q}%"))
    return conditions
```

- [ ] **Step 4: Update `list_monsters` and `RandomRequest`**

In `list_monsters`, replace the `product_id: int | None = None` parameter with:

```python
    product_ids: list[int] | None = Query(None),
```

and update the `_base_conditions` call (it passes positionally, so the third argument changes meaning):

```python
    conditions = _base_conditions(environment, system_profile, product_ids, review_status, hd_min, hd_max, q)
```

Add `Query` to the FastAPI import line:

```python
from fastapi import APIRouter, HTTPException, Query
```

In `RandomRequest`, replace `product_id: int | None = None` with:

```python
    product_ids: list[int] | None = None
```

and in `random_monsters`, replace `product_id=request.product_id,` with:

```python
        product_ids=request.product_ids,
```

- [ ] **Step 5: Add the books listing route**

Add this route immediately after the existing `@router.get("/environments")` route, so both literal paths sit before `/{entry_id}`:

```python
@router.get("/books")
async def list_books(db: DbSession, review_status: str = "confirmed") -> dict:
    """Books that have entries at the given review status, for the book filter.

    Takes review_status because a freshly extracted book has only pending
    entries: a confirmed-only listing would offer no books to filter by at
    exactly the moment you are reviewing that book.
    """
    query = (
        select(MonsterEntry.product_id, Product.title, func.count(MonsterEntry.id))
        .join(Product, Product.id == MonsterEntry.product_id)
        .where(MonsterEntry.review_status == review_status)
        .group_by(MonsterEntry.product_id, Product.title)
        .order_by(Product.title)
    )
    rows = (await db.execute(query)).all()
    return {
        "books": [
            {"product_id": product_id, "title": title, "count": count}
            for product_id, title, count in rows
        ]
    }
```

- [ ] **Step 6: Run tests to verify they pass**

From `backend/`: `python -m pytest tests/test_monsters_books.py -v`
Expected: 6 PASS

- [ ] **Step 7: Run the existing bestiary API tests for regressions**

From `backend/`: `python -m pytest tests/test_monsters_api.py -v`
Expected: all PASS. `test_monsters_api.py` does not pass `product_id` to `list_monsters` or `RandomRequest`, so it should be unaffected. If any test does reference `product_id`, update that call to `product_ids=[...]` — this parameter rename is intentional and approved.

- [ ] **Step 8: Commit**

```bash
git add backend/grimoire/api/routes/monsters.py backend/tests/test_monsters_books.py backend/tests/test_monsters_api.py
git commit -m "feat(bestiary): multi-book filter and books listing"
```

---

### Task 3: Saved favorites

**Files:**
- Create: `backend/grimoire/models/bestiary_favorite.py`
- Modify: `backend/grimoire/models/__init__.py`
- Modify: `backend/grimoire/api/routes/monsters.py`
- Test: `backend/tests/test_monsters_favorites.py` (create)

**Interfaces:**
- Consumes: `grimoire.database.Base`, `DbSession`
- Produces: `BestiaryFavorite` ORM class (table `bestiary_favorites`, columns `id`, `name`, `config`, `created_at`, `updated_at`); `class FavoriteRequest(BaseModel)` with `name: str | None`, `config: dict | None`; `async list_favorites(db) -> dict`, `async create_favorite(db, request) -> dict`, `async update_favorite(db, favorite_id, request) -> dict`, `async delete_favorite(db, favorite_id) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_monsters_favorites.py
"""Tests for saved bestiary queries."""

import pytest
from fastapi import HTTPException

from grimoire.api.routes.monsters import (
    FavoriteRequest,
    create_favorite,
    delete_favorite,
    list_favorites,
    update_favorite,
)

SAMPLE_CONFIG = {
    "product_ids": [13, 27],
    "environment": "forest",
    "system_profile": "dcc",
    "hd_min": 1.0,
    "hd_max": 3.0,
    "q": None,
    "table_size": 8,
}


async def test_create_and_list_favorite_round_trips_config(db):
    created = await create_favorite(
        db=db, request=FavoriteRequest(name="Woodland low-level", config=SAMPLE_CONFIG)
    )
    assert created["name"] == "Woodland low-level"
    # config must survive the JSON-in-Text round trip exactly
    assert created["config"] == SAMPLE_CONFIG

    listed = await list_favorites(db=db)
    match = [f for f in listed["favorites"] if f["id"] == created["id"]]
    assert len(match) == 1
    assert match[0]["config"]["product_ids"] == [13, 27]
    assert match[0]["config"]["table_size"] == 8


async def test_update_favorite_renames_without_touching_config(db):
    created = await create_favorite(
        db=db, request=FavoriteRequest(name="Original Name", config=SAMPLE_CONFIG)
    )
    updated = await update_favorite(
        db=db, favorite_id=created["id"], request=FavoriteRequest(name="Renamed")
    )
    assert updated["name"] == "Renamed"
    assert updated["config"] == SAMPLE_CONFIG


async def test_update_favorite_overwrites_config(db):
    created = await create_favorite(
        db=db, request=FavoriteRequest(name="Overwrite Me", config=SAMPLE_CONFIG)
    )
    new_config = {**SAMPLE_CONFIG, "environment": "swamp", "table_size": 12}
    updated = await update_favorite(
        db=db, favorite_id=created["id"], request=FavoriteRequest(config=new_config)
    )
    assert updated["config"]["environment"] == "swamp"
    assert updated["config"]["table_size"] == 12
    assert updated["name"] == "Overwrite Me"


async def test_delete_favorite(db):
    created = await create_favorite(
        db=db, request=FavoriteRequest(name="Delete Me", config=SAMPLE_CONFIG)
    )
    result = await delete_favorite(db=db, favorite_id=created["id"])
    assert result["deleted"] is True

    listed = await list_favorites(db=db)
    assert all(f["id"] != created["id"] for f in listed["favorites"])


async def test_create_favorite_requires_a_name(db):
    with pytest.raises(HTTPException) as exc:
        await create_favorite(db=db, request=FavoriteRequest(config=SAMPLE_CONFIG))
    assert exc.value.status_code == 422


async def test_update_unknown_favorite_is_404(db):
    with pytest.raises(HTTPException) as exc:
        await update_favorite(db=db, favorite_id=99999999, request=FavoriteRequest(name="Ghost"))
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/`: `python -m pytest tests/test_monsters_favorites.py -v`
Expected: FAIL with `ImportError: cannot import name 'FavoriteRequest'`

- [ ] **Step 3: Write the model and register it**

```python
# backend/grimoire/models/bestiary_favorite.py
"""BestiaryFavorite model - a saved bestiary query (see bestiary scoping spec)."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from grimoire.database import Base


class BestiaryFavorite(Base):
    """A named, saved bestiary query.

    `config` is JSON-in-Text (the ProcessingQueue.config convention) holding
    the whole query: product_ids, environment, system_profile, hd_min, hd_max,
    q, and table_size. review_status is deliberately excluded - it is a
    workflow toggle, not part of a question about monsters.
    """

    __tablename__ = "bestiary_favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[str] = mapped_column(Text, nullable=False)  # JSON object

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<BestiaryFavorite(id={self.id}, name='{self.name}')>"
```

In `backend/grimoire/models/__init__.py`, add the import alongside the others:

```python
from grimoire.models.bestiary_favorite import BestiaryFavorite
```

and add `"BestiaryFavorite"` to `__all__`.

- [ ] **Step 4: Add the favorites routes**

In `backend/grimoire/api/routes/monsters.py`, add the request model after `BulkStatusRequest`:

```python
class FavoriteRequest(BaseModel):
    name: str | None = None
    config: dict | None = None
```

Import the model at the top of the file by extending the existing models import:

```python
from grimoire.models import BestiaryFavorite, MonsterEntry, ProcessingQueue, Product
```

Add these routes. They MUST be declared before `@router.patch("/{entry_id}")` and `@router.get("/{entry_id}/metrics")`:

```python
def _favorite_to_dict(favorite: BestiaryFavorite) -> dict:
    return {
        "id": favorite.id,
        "name": favorite.name,
        "config": json.loads(favorite.config) if favorite.config else {},
    }


@router.get("/favorites")
async def list_favorites(db: DbSession) -> dict:
    """Saved bestiary queries, newest first."""
    result = await db.execute(
        select(BestiaryFavorite).order_by(BestiaryFavorite.created_at.desc(), BestiaryFavorite.id.desc())
    )
    return {"favorites": [_favorite_to_dict(f) for f in result.scalars().all()]}


@router.post("/favorites")
async def create_favorite(db: DbSession, request: FavoriteRequest) -> dict:
    """Save the current query under a name."""
    if not request.name or not request.name.strip():
        raise HTTPException(status_code=422, detail="name is required")

    favorite = BestiaryFavorite(
        name=request.name.strip(),
        config=json.dumps(request.config or {}),
    )
    db.add(favorite)
    await db.commit()
    await db.refresh(favorite)
    return _favorite_to_dict(favorite)


@router.patch("/favorites/{favorite_id}")
async def update_favorite(db: DbSession, favorite_id: int, request: FavoriteRequest) -> dict:
    """Rename a favorite, overwrite its query, or both."""
    result = await db.execute(select(BestiaryFavorite).where(BestiaryFavorite.id == favorite_id))
    favorite = result.scalar_one_or_none()
    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite not found")

    if request.name is not None:
        if not request.name.strip():
            raise HTTPException(status_code=422, detail="name cannot be blank")
        favorite.name = request.name.strip()
    if request.config is not None:
        favorite.config = json.dumps(request.config)

    await db.commit()
    await db.refresh(favorite)
    return _favorite_to_dict(favorite)


@router.delete("/favorites/{favorite_id}")
async def delete_favorite(db: DbSession, favorite_id: int) -> dict:
    """Remove a saved query."""
    result = await db.execute(select(BestiaryFavorite).where(BestiaryFavorite.id == favorite_id))
    favorite = result.scalar_one_or_none()
    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite not found")

    await db.delete(favorite)
    await db.commit()
    return {"deleted": True}
```

- [ ] **Step 5: Run tests to verify they pass**

From `backend/`: `python -m pytest tests/test_monsters_favorites.py -v`
Expected: 6 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/models/bestiary_favorite.py backend/grimoire/models/__init__.py backend/grimoire/api/routes/monsters.py backend/tests/test_monsters_favorites.py
git commit -m "feat(bestiary): saved query favorites"
```

---

### Task 4: Extraction guard

**Files:**
- Modify: `backend/grimoire/api/routes/monsters.py`
- Modify: `backend/grimoire/services/queue_processor.py`
- Test: `backend/tests/test_monsters_guard.py` (create)

**Interfaces:**
- Consumes: `segment_pages` and `PROFILES` (from Task 4 and Task 2 of the bestiary plan), `get_extracted_pages` from `grimoire.services.processor`, `TaskError` from `grimoire.services.queue_processor`
- Produces: `_profile_candidate_counts(pages) -> dict[str, int]`; `enqueue_extract` gains guard behaviour and returns `counts` (and optionally `warning`); `handle_monster_extract_task` raises `TaskError` on zero candidates

Guard thresholds, copied verbatim from the spec: zero candidates for the chosen profile → 400. Chosen profile finds **fewer than half** the best-scoring profile **and** the best finds **at least 20** → queue with a warning. Otherwise queue silently.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_monsters_guard.py
"""Tests for the wrong-profile extraction guard."""

import pytest
from fastapi import HTTPException

from grimoire.api.routes.monsters import ExtractRequest, enqueue_extract
from grimoire.models import Product
from grimoire.services.queue_processor import TaskError, handle_monster_extract_task

# A DCC inline stat line - what the dcc profile's anchor is built for.
DCC_MARKDOWN = (
    "## Orc\n\nRaiders of the wastes.\n\n"
    "Orc: Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; MV 30'; Act 1d20; "
    "SV Fort +1, Ref +0, Will -1; AL C.\n"
)

# A D&D 5e stat block - no "Init +N", no "HD NdN", so no profile matches it.
FIVE_E_MARKDOWN = (
    "AKLASH\nLarge monstrosity, neutral\n"
    "Armor Class 11 (natural armor)\n"
    "Hit Points 51 (6d10 + 18)\n"
    "Speed 30 ft.\n"
    "Challenge 2\n"
)


async def make_product(db, path, title, extracted=True):
    product = Product(
        file_path=path, file_name=path.rsplit("/", 1)[-1], file_size=1,
        file_hash=path, title=title, text_extracted=extracted,
        extracted_text_path="/t/does-not-matter.json" if extracted else None,
    )
    db.add(product)
    await db.flush()
    return product


async def test_guard_blocks_when_no_profile_matches(db, monkeypatch):
    """A 5e bestiary queued as DCC must be refused, not silently completed."""
    product = await make_product(db, "/t/guard-5e.pdf", "5E Bestiary")
    monkeypatch.setattr(
        "grimoire.services.processor.get_extracted_pages",
        lambda p: [{"page": 1, "markdown": FIVE_E_MARKDOWN}],
    )

    with pytest.raises(HTTPException) as exc:
        await enqueue_extract(db=db, product_id=product.id, request=ExtractRequest(system_profile="dcc"))
    assert exc.value.status_code == 400
    assert "stat block" in exc.value.detail.lower()


async def test_guard_allows_a_matching_profile(db, monkeypatch):
    product = await make_product(db, "/t/guard-dcc.pdf", "DCC Bestiary")
    monkeypatch.setattr(
        "grimoire.services.processor.get_extracted_pages",
        lambda p: [{"page": n, "markdown": DCC_MARKDOWN} for n in range(1, 6)],
    )

    result = await enqueue_extract(
        db=db, product_id=product.id, request=ExtractRequest(system_profile="dcc")
    )
    assert result["queued"] is True
    assert result["counts"]["dcc"] > 0
    assert "warning" not in result


async def test_guard_reports_counts_for_every_profile(db, monkeypatch):
    product = await make_product(db, "/t/guard-counts.pdf", "Counts Bestiary")
    monkeypatch.setattr(
        "grimoire.services.processor.get_extracted_pages",
        lambda p: [{"page": n, "markdown": DCC_MARKDOWN} for n in range(1, 4)],
    )

    result = await enqueue_extract(
        db=db, product_id=product.id, request=ExtractRequest(system_profile="dcc")
    )
    assert set(result["counts"].keys()) == {"dcc", "osr"}


async def test_handler_fails_on_zero_candidates(db, monkeypatch):
    """Zero candidates must not report success - that is the silent failure."""
    product = await make_product(db, "/t/guard-handler-zero.pdf", "Zero Candidates")
    monkeypatch.setattr(
        "grimoire.services.processor.get_extracted_pages",
        lambda p: [{"page": 1, "markdown": FIVE_E_MARKDOWN}],
    )

    async def _no_db_key(key_name):
        return "unused-because-we-fail-first"

    monkeypatch.setattr(
        "grimoire.processors.monster_normalizer.get_setting_from_db", _no_db_key
    )

    with pytest.raises(TaskError):
        await handle_monster_extract_task(db, product, config={"system_profile": "dcc"})
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/`: `python -m pytest tests/test_monsters_guard.py -v`
Expected: FAIL — `test_guard_blocks_when_no_profile_matches` fails because nothing raises, and `test_guard_allows_a_matching_profile` fails with `KeyError: 'counts'`.

- [ ] **Step 3: Add the dry-run helper and guard to `enqueue_extract`**

In `backend/grimoire/api/routes/monsters.py`, add this helper just above `enqueue_extract`:

```python
def _profile_candidate_counts(pages: list[dict]) -> dict[str, int]:
    """Candidate count per registered profile. Pure regex, no LLM - free to run."""
    from grimoire.processors.monster_segmenter import segment_pages

    return {pid: len(segment_pages(pages, profile)) for pid, profile in PROFILES.items()}
```

Then replace the body of `enqueue_extract` between the `text_extracted` check and the duplicate-queue check with the guard. The full route becomes:

```python
@router.post("/extract/{product_id}")
async def enqueue_extract(db: DbSession, product_id: int, request: ExtractRequest) -> dict:
    """Queue monster extraction, refusing profiles that cannot possibly work.

    Keys off content, not game_system metadata: metadata is unreliable (one
    known product is labelled Old-School Essentials while being byte-identical
    to a DCC book). Metadata only phrases the error message.
    """
    from grimoire.services import processor as _processor

    if request.system_profile not in PROFILES:
        raise HTTPException(status_code=400, detail=f"Unknown system profile: {request.system_profile}")

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not product.text_extracted:
        raise HTTPException(status_code=400, detail="Product has no extracted text")

    pages = _processor.get_extracted_pages(product)
    if not pages:
        raise HTTPException(
            status_code=400,
            detail="Product has no page-anchored text. Re-run text extraction first.",
        )

    counts = _profile_candidate_counts(pages)
    chosen = counts.get(request.system_profile, 0)
    if chosen == 0:
        supported = ", ".join(p.label for p in PROFILES.values())
        detail = (
            f"No stat blocks found in '{product.title or product.file_name}' using the "
            f"{PROFILES[request.system_profile].label} profile. Supported systems: {supported}."
        )
        if product.game_system:
            detail += f" This book is labelled '{product.game_system}'."
        raise HTTPException(status_code=400, detail=detail)

    existing = await db.execute(select(ProcessingQueue).where(
        ProcessingQueue.product_id == product_id,
        ProcessingQueue.task_type == "monster_extract",
        ProcessingQueue.status.in_(["pending", "processing"]),
    ))
    if existing.scalars().first():
        return {"queued": False, "message": "Extraction already queued for this product", "counts": counts}

    config = {"system_profile": request.system_profile}
    if request.provider:
        config["provider"] = request.provider
    if request.model:
        config["model"] = request.model
    db.add(ProcessingQueue(
        product_id=product_id,
        task_type="monster_extract",
        # Interactive, one-off, owner-triggered action — preempt bulk work
        # (text re-extraction etc. queues at priority=5) rather than sorting
        # to the back of that band behind thousands of backlog items.
        priority=9,
        status="pending",
        config=json.dumps(config),
    ))
    await db.commit()

    response = {
        "queued": True,
        "message": f"Monster extraction queued ({request.system_profile})",
        "counts": counts,
    }

    # Loose on purpose: the OSR anchor also matches DCC stat lines, so those
    # two counts do not separate cleanly. This catches DCC-vs-5e-scale
    # mistakes, and only ever warns.
    best_profile = max(counts, key=lambda k: counts[k])
    best = counts[best_profile]
    if best >= 20 and chosen * 2 < best:
        response["warning"] = (
            f"Queued with the {PROFILES[request.system_profile].label} profile "
            f"({chosen} stat blocks), but {PROFILES[best_profile].label} found {best}. "
            "Wrong profile?"
        )
    return response
```

- [ ] **Step 4: Make the handler fail on zero candidates**

In `backend/grimoire/services/queue_processor.py`, inside `handle_monster_extract_task`, find this line:

```python
    logger.info(f"monster_extract: {len(candidates)} candidates in '{product.file_name}'")
```

and add immediately after it:

```python
    if not candidates:
        # Reporting success here is the silent failure this guard exists to
        # remove: a wrong-profile run saves nothing and the queue says
        # "completed" with no signal to the owner.
        raise TaskError(
            f"monster_extract: no stat blocks found in '{product.file_name}' "
            f"using the '{profile_id}' profile"
        )
```

- [ ] **Step 5: Fix the two existing enqueue tests the guard breaks**

The guard makes `enqueue_extract` require real page-anchored text. `tests/test_monsters_api.py` seeds products with `extracted_text_path="/t/x.json"`, a path that does not exist, so `get_extracted_pages` returns `None` and both enqueue tests now hit the new 400. This is expected — the tests predate the guard — so update them to supply pages.

In `backend/tests/test_monsters_api.py`, add this constant near the top:

```python
DCC_GUARD_MARKDOWN = (
    "## Orc\n\nRaiders of the wastes.\n\n"
    "Orc: Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; MV 30'; Act 1d20; "
    "SV Fort +1, Ref +0, Will -1; AL C.\n"
)
```

Change `test_enqueue_extract` and `test_enqueue_rejects_unknown_profile` to take `monkeypatch` and stub the pages before calling `enqueue_extract`:

```python
async def test_enqueue_extract(db, monkeypatch):
    product, _ = await seed(db, "/t/api-enq.pdf", "Enq Orc", "forest")
    monkeypatch.setattr(
        "grimoire.services.processor.get_extracted_pages",
        lambda p: [{"page": n, "markdown": DCC_GUARD_MARKDOWN} for n in range(1, 4)],
    )
    ...  # rest of the test body is unchanged
```

`test_enqueue_rejects_unknown_profile` needs the same `monkeypatch` parameter and stub, even though it asserts a 400: the unknown-profile check runs before the guard, but stubbing keeps the test asserting the reason it means to assert rather than passing for the wrong one.

- [ ] **Step 6: Run tests to verify they pass**

From `backend/`: `python -m pytest tests/test_monsters_guard.py tests/test_monsters_api.py -v`
Expected: 4 PASS in the guard file, all PASS in the API file.

- [ ] **Step 7: Run the full backend suite**

From `backend/`: `python -m pytest -q`
Expected: baseline 323 + the 21 tests added in Tasks 1-4 = **344 passed, 6 failed** (the 6 pre-existing). Record the counts. If any test outside these files fails, stop and report.

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/api/routes/monsters.py backend/grimoire/services/queue_processor.py backend/tests/test_monsters_guard.py
git commit -m "feat(bestiary): guard against extracting with the wrong system profile"
```

---

### Task 5: Frontend API client

**Files:**
- Modify: `frontend/src/api/monsters.ts`

**Interfaces:**
- Consumes: the endpoints from Tasks 1-4
- Produces: `bulkSetStatus`, `listBooks`, `listFavorites`, `createFavorite`, `updateFavorite`, `deleteFavorite`, an updated `queueExtraction`, and `MonsterFilters.product_ids`; types `BestiaryBook`, `BestiaryFavorite`, `FavoriteConfig`, `ExtractResult`

- [ ] **Step 1: Update the client**

In `frontend/src/api/monsters.ts`, add `product_ids` to `MonsterFilters`:

```typescript
export interface MonsterFilters {
  environment?: string;
  system_profile?: string;
  product_ids?: number[];
  review_status?: string;
  q?: string;
  hd_min?: number;
  hd_max?: number;
  page?: number;
  per_page?: number;
}
```

`listMonsters` passes filters straight to axios `params`. Axios serialises an array as `product_ids[]=1&product_ids[]=2` by default, which FastAPI does NOT parse into `list[int]`. Set the repeat format explicitly:

```typescript
export async function listMonsters(filters: MonsterFilters) {
  const { data } = await api.get<{ items: MonsterEntry[]; total: number }>('/monsters', {
    params: filters,
    // FastAPI's list[int] expects repeated bare keys (product_ids=1&product_ids=2);
    // axios would otherwise emit product_ids[]=1 and the param would be dropped.
    paramsSerializer: { indexes: null },
  });
  return data;
}
```

Then append the new functions and types:

```typescript
export interface BestiaryBook {
  product_id: number;
  title: string | null;
  count: number;
}

export interface FavoriteConfig {
  product_ids?: number[];
  environment?: string;
  system_profile?: string;
  hd_min?: number;
  hd_max?: number;
  q?: string;
  table_size?: number;
}

export interface BestiaryFavorite {
  id: number;
  name: string;
  config: FavoriteConfig;
}

export interface ExtractResult {
  queued: boolean;
  message: string;
  counts?: Record<string, number>;
  warning?: string;
}

export async function bulkSetStatus(ids: number[], reviewStatus: string) {
  const { data } = await api.post<{ updated: number }>('/monsters/bulk-status', {
    ids,
    review_status: reviewStatus,
  });
  return data.updated;
}

export async function listBooks(reviewStatus = 'confirmed') {
  const { data } = await api.get<{ books: BestiaryBook[] }>('/monsters/books', {
    params: { review_status: reviewStatus },
  });
  return data.books;
}

export async function listFavorites() {
  const { data } = await api.get<{ favorites: BestiaryFavorite[] }>('/monsters/favorites');
  return data.favorites;
}

export async function createFavorite(name: string, config: FavoriteConfig) {
  const { data } = await api.post<BestiaryFavorite>('/monsters/favorites', { name, config });
  return data;
}

export async function updateFavorite(
  id: number,
  patch: { name?: string; config?: FavoriteConfig },
) {
  const { data } = await api.patch<BestiaryFavorite>(`/monsters/favorites/${id}`, patch);
  return data;
}

export async function deleteFavorite(id: number) {
  await api.delete(`/monsters/favorites/${id}`);
}
```

Update `rollRandom`, whose parameter type still names the singular `product_id` that Task 2 removed from the API. Without this the book scope is silently dropped from every roll:

```typescript
export async function rollRandom(params: {
  count: number;
  environment?: string;
  system_profile?: string;
  hd_min?: number;
  hd_max?: number;
  product_ids?: number[];
}) {
  const { data } = await api.post<{ items: MonsterEntry[] }>('/monsters/random', params);
  return data.items;
}
```

Finally, replace the existing `queueExtraction` so callers can read the counts and warning:

```typescript
export async function queueExtraction(productId: number, systemProfile: string) {
  const { data } = await api.post<ExtractResult>(
    `/monsters/extract/${productId}`,
    { system_profile: systemProfile },
  );
  return data;
}
```

- [ ] **Step 2: Type-check**

From `frontend/`: `npx tsc -b --force`
Expected: only the pre-existing `Settings.tsx` 'Shield' error.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/monsters.ts
git commit -m "feat(bestiary): API client for bulk status, books, and favorites"
```

---

### Task 6: Bulk review selection UI

**Files:**
- Modify: `frontend/src/pages/Bestiary.tsx`

**Interfaces:**
- Consumes: `bulkSetStatus` (Task 5), the existing `items` array and `reviewMode` flag
- Produces: checkbox selection state and a footer action bar, shown only in review mode

"Unflagged" means `flags.length === 0` **and** `extraction_confidence >= 0.8`. Both are required: the single genuinely bad entry in a 184-entry batch had no flags and was identifiable only by its 0.65 confidence.

- [ ] **Step 1: Add selection state and the bulk mutation**

In `frontend/src/pages/Bestiary.tsx`, add to the imports from `../api/monsters`: `bulkSetStatus`.

Add this state alongside the existing `useState` declarations:

```tsx
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
```

Add this mutation next to `patchMutation`:

```tsx
  const bulkMutation = useMutation({
    mutationFn: ({ ids, status }: { ids: number[]; status: string }) =>
      bulkSetStatus(ids, status),
    onSuccess: () => {
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: ['monsters'] });
      queryClient.invalidateQueries({ queryKey: ['monster-books'] });
    },
  });
```

Add these helpers after the `roll` function:

```tsx
  const UNFLAGGED_MIN_CONFIDENCE = 0.8;

  const isUnflagged = (entry: MonsterEntry) =>
    entry.flags.length === 0 && (entry.extraction_confidence ?? 0) >= UNFLAGGED_MIN_CONFIDENCE;

  const toggleSelected = (id: number) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const selectAll = () => setSelectedIds(new Set(items.map((e) => e.id)));
  const selectUnflagged = () =>
    setSelectedIds(new Set(items.filter(isUnflagged).map((e) => e.id)));
  const clearSelection = () => setSelectedIds(new Set());
```

- [ ] **Step 2: Add the selection toolbar**

Insert this block immediately before the `<div className="space-y-2">` that renders the entry list:

```tsx
      {reviewMode && items.length > 0 && (
        <div className="flex items-center gap-3 mb-2 text-sm">
          <button className="px-2 py-1 rounded border" style={{ borderColor: 'var(--color-border)' }}
            onClick={selectAll}>Select all ({items.length})</button>
          <button className="px-2 py-1 rounded border" style={{ borderColor: 'var(--color-border)' }}
            onClick={selectUnflagged}>
            Select all unflagged ({items.filter(isUnflagged).length})
          </button>
          {selectedIds.size > 0 && (
            <button className="px-2 py-1 opacity-70" onClick={clearSelection}>Clear</button>
          )}
        </div>
      )}
```

- [ ] **Step 3: Add a checkbox to each row**

In the entry list, the row header currently starts with:

```tsx
            <div className="flex items-center justify-between cursor-pointer"
              onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}>
              <div>
```

Replace that opening with a version that puts the checkbox outside the click-to-expand region, so ticking a box does not also expand the row:

```tsx
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 flex-1 cursor-pointer"
                onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}>
                {reviewMode && (
                  <input
                    type="checkbox"
                    checked={selectedIds.has(entry.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggleSelected(entry.id)}
                  />
                )}
                <div>
```

and close the extra `<div>` by adding one more `</div>` immediately after the existing closing tag of that inner name block (the `</div>` that follows the `<span>` showing book and page).

- [ ] **Step 4: Add the footer action bar**

Insert immediately after the entry-list `</div>`:

```tsx
      {reviewMode && selectedIds.size > 0 && (
        <div className="sticky bottom-0 mt-3 flex items-center gap-3 p-3 rounded border"
          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface-raised)' }}>
          <span className="text-sm">{selectedIds.size} selected</span>
          <button className="px-3 py-1 rounded border" style={{ borderColor: 'var(--color-border)' }}
            disabled={bulkMutation.isPending}
            onClick={() => bulkMutation.mutate({ ids: [...selectedIds], status: 'confirmed' })}>
            Confirm {selectedIds.size}
          </button>
          <button className="px-3 py-1 rounded border opacity-80" style={{ borderColor: 'var(--color-border)' }}
            disabled={bulkMutation.isPending}
            onClick={() => bulkMutation.mutate({ ids: [...selectedIds], status: 'rejected' })}>
            Reject {selectedIds.size}
          </button>
        </div>
      )}
```

- [ ] **Step 5: Clear selection when the filters change**

In the existing `setFilter` helper, add `setSelectedIds(new Set());` alongside the existing `setFilters(...)` call, so a selection cannot survive into a different result set.

- [ ] **Step 6: Type-check**

From `frontend/`: `npx tsc -b --force`
Expected: only the pre-existing `Settings.tsx` 'Shield' error.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Bestiary.tsx
git commit -m "feat(bestiary): bulk confirm and reject in review mode"
```

---

### Task 7: MultiCombobox component

**Files:**
- Create: `frontend/src/components/MultiCombobox.tsx`

**Interfaces:**
- Consumes: nothing (a leaf component; `lucide-react` is already a dependency)
- Produces:

```typescript
export interface MultiComboboxOption {
  id: number;
  label: string;
  count?: number;
}

export function MultiCombobox(props: {
  options: MultiComboboxOption[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  placeholder?: string;
  emptyLabel?: string;
  className?: string;
}): JSX.Element
```

Mirrors the interaction model of the existing `ComboboxWithAdd.tsx`: filter-as-you-type, arrow-key highlight, Enter to pick, Escape to close, and a `mousedown` listener that closes on click-outside. Differences: the value is `number[]`, picking an option toggles it and keeps the popup open, selections render as removable chips in the trigger, and there is no add-new option (you cannot invent a book).

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/components/MultiCombobox.tsx
import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Check, X } from 'lucide-react';

export interface MultiComboboxOption {
  id: number;
  label: string;
  count?: number;
}

interface MultiComboboxProps {
  options: MultiComboboxOption[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  placeholder?: string;
  emptyLabel?: string;
  className?: string;
}

/**
 * Searchable multi-select. Sibling of ComboboxWithAdd rather than a mode of
 * it: the value type, trigger rendering, close-on-pick behaviour and add-new
 * path all differ, and ComboboxWithAdd is load-bearing in ProductDetail.
 */
export function MultiCombobox({
  options,
  selectedIds,
  onChange,
  placeholder = 'Search...',
  emptyLabel = 'All',
  className = '',
}: MultiComboboxProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = options.filter((o) =>
    o.label.toLowerCase().includes(search.toLowerCase())
  );
  const selected = options.filter((o) => selectedIds.includes(o.id));

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setSearch('');
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    setHighlightedIndex(-1);
  }, [search, isOpen]);

  const toggle = (id: number) => {
    // Stays open: picking several books in a row is the normal case.
    onChange(selectedIds.includes(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id]);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        setIsOpen(true);
        e.preventDefault();
      }
      return;
    }
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setHighlightedIndex((prev) => (prev < filtered.length - 1 ? prev + 1 : prev));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : prev));
        break;
      case 'Enter':
        e.preventDefault();
        if (highlightedIndex >= 0 && filtered[highlightedIndex]) {
          toggle(filtered[highlightedIndex].id);
        }
        break;
      case 'Backspace':
        // Only when the box is empty, so it never eats a character mid-search.
        if (search === '' && selectedIds.length > 0) {
          onChange(selectedIds.slice(0, -1));
        }
        break;
      case 'Escape':
        setIsOpen(false);
        setSearch('');
        break;
    }
  };

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <div
        className="flex items-center gap-1 flex-wrap rounded-md px-2 py-1 text-sm cursor-text"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          minHeight: '34px',
        }}
        onClick={() => {
          setIsOpen(true);
          inputRef.current?.focus();
        }}
      >
        {selected.map((option) => (
          <span
            key={option.id}
            className="inline-flex items-center gap-1 px-1.5 rounded text-xs"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-primary)' }}
          >
            {option.label}
            <button
              type="button"
              aria-label={`Remove ${option.label}`}
              onClick={(e) => {
                e.stopPropagation();
                onChange(selectedIds.filter((x) => x !== option.id));
              }}
            >
              <X size={12} />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          type="text"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            if (!isOpen) setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={selected.length === 0 ? emptyLabel : placeholder}
          className="flex-1 outline-none bg-transparent min-w-[80px]"
          style={{ color: 'var(--color-text-primary)' }}
        />
        <ChevronDown
          className={`shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          size={14}
          style={{ color: 'var(--color-text-secondary)' }}
        />
      </div>

      {isOpen && (
        <div
          className="absolute z-50 mt-1 w-full rounded-md shadow-lg max-h-60 overflow-auto"
          style={{
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          {filtered.length === 0 ? (
            <div className="px-3 py-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              No matches
            </div>
          ) : (
            <ul role="listbox" aria-multiselectable="true">
              {filtered.map((option, index) => {
                const isSelected = selectedIds.includes(option.id);
                return (
                  <li
                    key={option.id}
                    role="option"
                    aria-selected={isSelected}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer"
                    style={{
                      backgroundColor:
                        highlightedIndex === index ? 'var(--color-accent-light)' : 'transparent',
                      color: 'var(--color-text-primary)',
                    }}
                    onClick={() => toggle(option.id)}
                    onMouseEnter={() => setHighlightedIndex(index)}
                  >
                    {isSelected ? (
                      <Check size={14} style={{ color: 'var(--color-accent)' }} />
                    ) : (
                      <span className="w-[14px]" />
                    )}
                    <span className="flex-1">{option.label}</span>
                    {option.count !== undefined && (
                      <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                        {option.count}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

From `frontend/`: `npx tsc -b --force`
Expected: only the pre-existing `Settings.tsx` 'Shield' error. The component is not yet imported anywhere, so this only proves it compiles.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/MultiCombobox.tsx
git commit -m "feat(ui): searchable multi-select combobox"
```

---

### Task 8: Book filter and favorites UI

**Files:**
- Modify: `frontend/src/pages/Bestiary.tsx`

**Interfaces:**
- Consumes: `listBooks`, `listFavorites`, `createFavorite`, `deleteFavorite`, types `BestiaryBook`, `BestiaryFavorite`, `FavoriteConfig` (Task 5)
- Produces: a book multi-select in the filter bar and a favorites strip

- [ ] **Step 1: Add the queries and mutations**

Extend the `../api/monsters` import with: `listBooks`, `listFavorites`, `createFavorite`, `deleteFavorite`, and the types `BestiaryFavorite`, `FavoriteConfig`.

Add these queries next to the existing ones:

```tsx
  const { data: books = [] } = useQuery({
    queryKey: ['monster-books', filters.review_status ?? 'confirmed'],
    queryFn: () => listBooks(filters.review_status ?? 'confirmed'),
  });
  const { data: favorites = [] } = useQuery({
    queryKey: ['monster-favorites'],
    queryFn: listFavorites,
  });
```

Add these mutations:

```tsx
  const saveFavoriteMutation = useMutation({
    mutationFn: ({ name, config }: { name: string; config: FavoriteConfig }) =>
      createFavorite(name, config),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monster-favorites'] }),
  });
  const deleteFavoriteMutation = useMutation({
    mutationFn: (id: number) => deleteFavorite(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monster-favorites'] }),
  });
```

- [ ] **Step 2: Add the book multi-select**

Import the component from Task 7:

```tsx
import { MultiCombobox } from '../components/MultiCombobox';
```

Add this to the filter bar, before the environment `<select>`. The component renders its own removable chips, so no separate chip row is needed:

```tsx
        <MultiCombobox
          className="min-w-[220px]"
          options={books.map((b) => ({
            id: b.product_id,
            label: b.title ?? `Book ${b.product_id}`,
            count: b.count,
          }))}
          selectedIds={filters.product_ids ?? []}
          onChange={(ids) => setFilter({ product_ids: ids.length > 0 ? ids : undefined })}
          emptyLabel="All books"
          placeholder="Search books..."
        />
```

`ids.length > 0 ? ids : undefined` matters: an empty array would serialise as no parameter anyway, but sending `undefined` keeps the filter object clean and keeps the React Query key stable between "never set" and "cleared".

- [ ] **Step 3: Add the favorites strip**

Insert immediately above the filter bar `<div>`:

```tsx
      <div className="flex gap-2 items-center flex-wrap mb-3">
        {favorites.map((fav: BestiaryFavorite) => (
          <span key={fav.id} className="inline-flex items-center gap-1 text-sm px-2 py-1 rounded border"
            style={{ borderColor: 'var(--color-border)' }}>
            <button onClick={() => applyFavorite(fav)}>★ {fav.name}</button>
            <button className="opacity-70" title="Apply and roll"
              onClick={() => { applyFavorite(fav); roll(fav.config.table_size ?? tableSize); }}>
              Run
            </button>
            <button className="opacity-50" title="Delete"
              onClick={() => deleteFavoriteMutation.mutate(fav.id)}>×</button>
          </span>
        ))}
        <button className="text-sm px-2 py-1 rounded border" style={{ borderColor: 'var(--color-border)' }}
          onClick={saveCurrentQuery}>
          ★ Save current query
        </button>
      </div>
```

- [ ] **Step 4: Add the apply and save helpers**

Add these next to the other helpers:

```tsx
  const applyFavorite = (fav: BestiaryFavorite) => {
    const { table_size, ...queryFilters } = fav.config;
    setFilters((prev) => ({ ...prev, ...queryFilters, page: 1 }));
    setRolled([]);
    setSelectedIds(new Set());
    if (table_size) setTableSize(table_size);
  };

  const saveCurrentQuery = () => {
    const name = window.prompt('Name this query');
    if (!name?.trim()) return;
    saveFavoriteMutation.mutate({
      name: name.trim(),
      config: {
        product_ids: filters.product_ids,
        environment: filters.environment,
        system_profile: filters.system_profile,
        hd_min: filters.hd_min,
        hd_max: filters.hd_max,
        q: filters.q,
        table_size: tableSize,
      },
    });
  };
```

Note `applyFavorite` sets filters directly rather than through `setFilter`, because `setFilter` merges one patch — applying a favorite must also clear filter keys the favorite does not set.

- [ ] **Step 5: Include books in the roll**

In the `roll` function, add `product_ids: filters.product_ids,` to the object passed to `rollRandom`, so encounter tables honour the book scope.

- [ ] **Step 6: Type-check**

From `frontend/`: `npx tsc -b --force`
Expected: only the pre-existing `Settings.tsx` 'Shield' error.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Bestiary.tsx
git commit -m "feat(bestiary): book filter and saved query favorites"
```

---

### Task 9: Extract as bestiary from the product modal

**Files:**
- Modify: `frontend/src/components/ProductDetail.tsx`

**Interfaces:**
- Consumes: `queueExtraction` and `ExtractResult` from `frontend/src/api/monsters` (Task 5)
- Produces: an "Extract as bestiary" button and inline confirmation in the Text tab's processing status bar

Place it in the processing status bar (around line 1546, the `{/* Processing Status Bar */}` block), NOT on the modal's `extract` tab — that tab belongs to the older structured-extraction prototype and is what caused the original confusion.

- [ ] **Step 1: Add imports and state**

At the top of `frontend/src/components/ProductDetail.tsx`, add:

```tsx
import { queueExtraction } from '../api/monsters';
```

Add this state alongside the component's other `useState` calls:

```tsx
  const [bestiaryProfile, setBestiaryProfile] = useState<'dcc' | 'osr'>('dcc');
  const [bestiaryMessage, setBestiaryMessage] = useState<string | null>(null);
```

Add this mutation next to the other mutations:

```tsx
  const bestiaryMutation = useMutation({
    mutationFn: () => queueExtraction(product.id, bestiaryProfile),
    onSuccess: (result) =>
      setBestiaryMessage(result.warning ? `${result.message} — ${result.warning}` : result.message),
    onError: (err: any) =>
      setBestiaryMessage(err?.response?.data?.detail ?? 'Failed to queue bestiary extraction'),
  });
```

- [ ] **Step 2: Pre-select the profile from the book's metadata**

Add this effect so a DCC-labelled book defaults to the DCC profile. Metadata is a hint for the default only — the guard decides what is actually allowed:

```tsx
  useEffect(() => {
    const system = (localProduct.game_system ?? '').toLowerCase();
    if (system.includes('dungeon crawl classics') || system.includes('dcc')) {
      setBestiaryProfile('dcc');
    } else if (
      system.includes('old-school') || system.includes('ose') ||
      system.includes('b/x') || system.includes('advanced dungeons')
    ) {
      setBestiaryProfile('osr');
    }
  }, [localProduct.game_system]);
```

- [ ] **Step 3: Add the button to the processing status bar**

In the Processing Status Bar block, after the existing "AI Identify" button's closing `)}`, add:

```tsx
                {localProduct.processing_status?.text_extracted && (
                  <div className="flex items-center gap-2">
                    <select
                      value={bestiaryProfile}
                      onChange={(e) => setBestiaryProfile(e.target.value as 'dcc' | 'osr')}
                      className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
                    >
                      <option value="dcc">DCC</option>
                      <option value="osr">OSR</option>
                    </select>
                    <button
                      onClick={() => { setBestiaryMessage(null); bestiaryMutation.mutate(); }}
                      disabled={bestiaryMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                    >
                      {bestiaryMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Skull className="h-4 w-4" />
                      )}
                      Extract as Bestiary
                    </button>
                  </div>
                )}
```

Add `Skull` to the existing `lucide-react` import at the top of the file.

The button is disabled while the request is in flight. That matters here: the guard's dry-run segments the whole book (~1.5s for 252 pages), so the endpoint is no longer instant and a double-click would repeat the work.

- [ ] **Step 4: Show the result message**

Immediately after the Processing Status Bar's closing `</div>`, add:

```tsx
              {bestiaryMessage && (
                <div className="mb-4 rounded-lg border p-3 text-sm"
                  style={{ borderColor: 'var(--color-border)' }}>
                  {bestiaryMessage}
                </div>
              )}
```

- [ ] **Step 5: Type-check**

From `frontend/`: `npx tsc -b --force`
Expected: only the pre-existing `Settings.tsx` 'Shield' error. If `useEffect` or `useMutation` is not already imported in this file, add it to the existing React / React Query import.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ProductDetail.tsx
git commit -m "feat(bestiary): queue extraction from the product detail modal"
```

---

### Task 10: Full verification

**Files:** none new.

- [ ] **Step 1: Full backend suite**

From `backend/`: `python -m pytest -q`
Expected: **344 passed, 6 failed** — the 6 pre-existing baseline failures and no others. Record the counts.

- [ ] **Step 2: Frontend type-check**

From `frontend/`: `npx tsc -b --force`
Expected: only `src/pages/Settings.tsx(3,137): error TS6133: 'Shield' is declared but its value is never read.`

- [ ] **Step 3: Confirm the working tree is clean**

```bash
git status --short
```

Expected: no stragglers beyond the owner's own pre-existing uncommitted changes (`backend/grimoire/processors/ai_identifier.py`, `docs/superpowers/specs/2026-03-13-folio-design.md`, and untracked scratch directories).

- [ ] **Step 4: Stop**

Integration (merge or PR) is decided with the owner via superpowers:finishing-a-development-branch — do not merge unprompted.

**Manual e2e (owner-driven, post-merge):** the app must be restarted for the worker to pick up the handler change — use `stop.bat` then `start-headless.bat`. Then: open a book in the Library, use "Extract as Bestiary", confirm the guard refuses a 5e book (product 3031, *5E HÂRN Bestiary*) and accepts a DCC one; in the Bestiary tab, filter to specific books, bulk-confirm with "select all unflagged", save a query as a favorite, and hit Run to regenerate its table.
