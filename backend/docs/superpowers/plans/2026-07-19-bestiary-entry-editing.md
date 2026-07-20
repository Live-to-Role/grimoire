# Bestiary Entry Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a human create, fully edit, duplicate and delete bestiary entries by hand, deriving the same computed fields extraction derives.

**Architecture:** Extract the pure "derive stats + flags" logic that today lives inside the LLM normalizer into a shared service function, then build `POST /api/v1/monsters` and `DELETE /api/v1/monsters/{entry_id}` on top of it. `PATCH /{entry_id}` switches from `if value is not None` to Pydantic's `model_fields_set` so an explicit `null` clears a field. The frontend gains a single controlled-state modal (`MonsterEntryModal`) used for all three of add / edit / duplicate, replacing nothing — the existing inline review editors stay.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Pydantic v2, pytest (`asyncio_mode = "auto"`), React 18 + TypeScript, React Query v5, Tailwind + CSS-variable theming.

## Global Constraints

- Route handlers commit explicitly — `get_db()` does **not** auto-commit.
- JSON-in-Text columns (`attacks`, `special_abilities`, `environments`, `flags`): `json.dumps` to store, `json.loads` to read.
- Declare literal paths (`/books`, `/random`, `/bulk-status`, …) **before** `/{entry_id}`-shaped routes in `monsters.py`.
- Route functions are called **directly** in tests with the `db` fixture; keep signatures compatible with direct invocation.
- **Never use a bare `= Query(...)` / `= Depends(...)` default** on a route function this codebase invokes directly in tests — the Python default becomes the `Query` object rather than `None`. Use `Annotated[T, Query()] = None`.
- Only `review_status == "confirmed"` entries feed browse, random and metrics.
- Hand-created entries: `extraction_confidence` is `None`, `review_status` is `"confirmed"`.
- Not in scope: free-form custom fields, per-system field definitions, editing `raw_text` or `system_profile`, user-editable `flags`.
- **Backend baseline (measured 2026-07-19, before any of this work): `346 passed, 6 failed`.** The 6 failures are pre-existing: `tests/api/test_diagnostics.py::test_diagnostics_returns_queue_stats`, `tests/api/test_diagnostics.py::test_diagnostics_returns_product_count`, `tests/api/test_products_list.py::test_count_query_does_not_include_selectinload`, `tests/services/test_scanner_batch.py::test_queue_products_uses_batch_insert`, `tests/test_backup_routes.py::test_get_status_unconfigured`, `tests/test_backup_routes.py::test_list_backups_empty`. Never let the failure count rise above 6.
- **Frontend gate:** `npx tsc -b` from `frontend/`, baseline clean (zero errors). There is no frontend test harness.
- All backend commands run from `backend/` with `python -m pytest` (miniconda python — **not** `.venv`, which has no pytest).

---

## File Structure

**Create:**
- `backend/grimoire/services/monster_fields.py` — pure derivation of `hd_value`, `hp_avg`, per-attack `damage_avg`, and validation `flags` from user-or-LLM-supplied stats. Single source of truth shared by the extractor and the create/patch routes.
- `backend/tests/test_monster_fields.py` — unit tests for that function.
- `backend/tests/test_monsters_crud.py` — tests for create / patch-null / delete.
- `frontend/src/components/MonsterEntryModal.tsx` — the controlled entry form modal.

**Modify:**
- `backend/grimoire/processors/monster_normalizer.py` — `build_entry_from_llm` delegates derivation to the new service.
- `backend/grimoire/api/routes/monsters.py` — add `CreateEntryRequest`, `create_entry`, `delete_entry`; rewrite `patch_entry` to use `model_fields_set`.
- `frontend/src/api/monsters.ts` — `createMonster`, `deleteMonster`, `MonsterEntryInput`.
- `frontend/src/pages/Bestiary.tsx` — Add entry button, per-row Edit / Duplicate / Delete, modal wiring, post-create view switch.

---

## Task 1: Shared stat-derivation service

Pulls the derived-field + flag logic out of the LLM normalizer so the create route computes them identically. No behaviour change to extraction.

**Files:**
- Create: `backend/grimoire/services/monster_fields.py`
- Create: `backend/tests/test_monster_fields.py`
- Modify: `backend/grimoire/processors/monster_normalizer.py:85-137`

**Interfaces:**
- Consumes: `grimoire.utils.dice.dice_average`, `grimoire.utils.dice.parse_dice`.
- Produces:
  ```python
  def derive_stats(
      ac: int | None,
      hd_dice: str | None,
      attacks: list[dict] | None,
  ) -> tuple[dict, list[str]]
  ```
  Returns `(fields, flags)` where `fields` has exactly the keys
  `ac: int | None`, `hd_dice: str | None`, `hd_value: float | None`,
  `hp_avg: float | None`, `attacks: list[dict]` (each attack a dict with
  `name: str`, `bonus: int | None`, `damage_dice: str | None`,
  `damage_avg: float | None`), and `flags` is a sorted, de-duplicated list
  drawn from `{"ac_out_of_range", "damage_unparseable", "hd_unparseable", "no_attacks"}`.
  Note `fields["attacks"]` is a **list**, not a JSON string — callers dump it.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_monster_fields.py`:

```python
"""Unit tests for shared monster stat derivation."""

from grimoire.services.monster_fields import derive_stats


def test_derives_hd_value_and_hp_avg():
    fields, flags = derive_stats(ac=13, hd_dice="3d6", attacks=[{"name": "bite", "damage_dice": "1d4"}])
    assert fields["hp_avg"] == 10.5
    assert fields["hd_value"] == 3.0
    assert fields["attacks"][0]["damage_avg"] == 2.5
    assert flags == []


def test_flags_no_attacks():
    _, flags = derive_stats(ac=13, hd_dice="1d8", attacks=[])
    assert flags == ["no_attacks"]


def test_flags_unparseable_hd_and_damage():
    fields, flags = derive_stats(
        ac=13, hd_dice="4d8 per 8 tentacles",
        attacks=[{"name": "sting", "damage_dice": "1d3 plus stun"}],
    )
    assert fields["hd_value"] is None
    assert fields["hp_avg"] is None
    assert fields["attacks"][0]["damage_avg"] is None
    assert flags == ["damage_unparseable", "hd_unparseable"]


def test_flags_ac_out_of_range():
    _, flags = derive_stats(ac=99, hd_dice="1d8", attacks=[{"name": "claw", "damage_dice": "1d4"}])
    assert flags == ["ac_out_of_range"]


def test_none_stats_are_tolerated():
    fields, flags = derive_stats(ac=None, hd_dice=None, attacks=None)
    assert fields["ac"] is None
    assert fields["hd_dice"] is None
    assert fields["hd_value"] is None
    assert fields["hp_avg"] is None
    assert fields["attacks"] == []
    assert flags == ["no_attacks"]


def test_attack_defaults_fill_missing_keys():
    fields, _ = derive_stats(ac=10, hd_dice="1d8", attacks=[{}])
    assert fields["attacks"][0] == {
        "name": "attack", "bonus": None, "damage_dice": None, "damage_avg": None,
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_monster_fields.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'grimoire.services.monster_fields'`

- [ ] **Step 3: Write the service**

Create `backend/grimoire/services/monster_fields.py`:

```python
"""Shared derivation of computed monster stats and validation flags.

Single source of truth for the numbers the bestiary shows. Both LLM
extraction (`monster_normalizer.build_entry_from_llm`) and hand-created /
hand-edited entries (the monsters API) route through here, so a typed-in
entry is flagged and scored exactly as an extracted one is.
"""

from grimoire.utils.dice import dice_average, parse_dice


def derive_stats(
    ac: int | None,
    hd_dice: str | None,
    attacks: list[dict] | None,
) -> tuple[dict, list[str]]:
    """Compute derived stat fields and validation flags.

    Returns (fields, flags). `fields["attacks"]` is a list of dicts — callers
    are responsible for `json.dumps` before storing it in the Text column.
    """
    flags: list[str] = []

    if ac is not None and not (0 <= int(ac) <= 30):
        flags.append("ac_out_of_range")

    normalized_attacks = []
    for atk in attacks or []:
        damage_dice = atk.get("damage_dice")
        damage_avg = dice_average(damage_dice)
        if damage_dice and damage_avg is None:
            flags.append("damage_unparseable")
        normalized_attacks.append({
            "name": atk.get("name") or "attack",
            "bonus": atk.get("bonus"),
            "damage_dice": damage_dice,
            "damage_avg": damage_avg,
        })
    if not normalized_attacks:
        flags.append("no_attacks")

    hp_avg = dice_average(hd_dice)
    parsed_hd = parse_dice(hd_dice)
    hd_value = float(parsed_hd[0]) if parsed_hd else None
    if hd_dice and parsed_hd is None:
        flags.append("hd_unparseable")

    fields = {
        "ac": int(ac) if ac is not None else None,
        "hd_dice": hd_dice,
        "hd_value": hd_value,
        "hp_avg": hp_avg,
        "attacks": normalized_attacks,
    }
    return fields, sorted(set(flags))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_monster_fields.py -q`
Expected: `6 passed`

- [ ] **Step 5: Refactor the normalizer to delegate**

In `backend/grimoire/processors/monster_normalizer.py`, replace the whole body of `build_entry_from_llm` (currently lines 85-137) with this. The LLM-specific parts (descending-AC normalization, THAC0 → bonus fallback) stay here; everything downstream of them moves to `derive_stats`:

```python
def build_entry_from_llm(llm: dict, candidate: Candidate, profile: SystemProfile) -> dict:
    """Pure normalization + validation of LLM output into MonsterEntry fields."""
    ac = llm.get("ac")
    if ac is not None and llm.get("ac_style") == "descending":
        ac = normalize_descending_ac(int(ac))

    # THAC0 → attack bonus is LLM-input-shaped, so it happens before the shared
    # derivation, which takes attacks with bonuses already resolved.
    thac0 = llm.get("thac0")
    raw_attacks = []
    for atk in llm.get("attacks") or []:
        bonus = atk.get("bonus")
        if bonus is None and thac0 is not None:
            bonus = normalize_thac0(int(thac0))
        raw_attacks.append({
            "name": atk.get("name"),
            "bonus": bonus,
            "damage_dice": atk.get("damage_dice"),
        })

    stats, flags = derive_stats(ac=ac, hd_dice=llm.get("hd_dice"), attacks=raw_attacks)

    return {
        "name": llm.get("name") or candidate.name_guess,
        "page_number": candidate.page,
        "system_profile": profile.id,
        "raw_text": candidate.raw_text,
        "ac": stats["ac"],
        "hd_dice": stats["hd_dice"],
        "hd_value": stats["hd_value"],
        "hp_avg": stats["hp_avg"],
        "attacks": json.dumps(stats["attacks"]),
        "move": llm.get("move"),
        "special_abilities": json.dumps(llm.get("special_abilities") or []),
        "environments": json.dumps(llm.get("environments") or []),
        "extraction_confidence": llm.get("confidence"),
        "flags": json.dumps(flags),
        "review_status": "pending",
    }
```

Update the imports at the top of that file — replace

```python
from grimoire.utils.dice import dice_average, parse_dice
```

with

```python
from grimoire.services.monster_fields import derive_stats
```

(`dice_average` and `parse_dice` are no longer referenced in this module; leaving them imported would be dead weight.)

- [ ] **Step 6: Verify the refactor changed no behaviour**

Run: `cd backend && python -m pytest tests/test_monster_normalizer.py tests/test_monster_extract_handler.py tests/test_monster_fields.py -q`
Expected: all pass, zero failures.

- [ ] **Step 7: Commit**

```bash
git add backend/grimoire/services/monster_fields.py backend/tests/test_monster_fields.py backend/grimoire/processors/monster_normalizer.py
git commit -m "refactor(bestiary): extract shared monster stat derivation"
```

---

## Task 2: `POST /api/v1/monsters` — create an entry by hand

**Files:**
- Modify: `backend/grimoire/api/routes/monsters.py`
- Create: `backend/tests/test_monsters_crud.py`

**Interfaces:**
- Consumes: `derive_stats` from Task 1; `_entry_to_dict`, `PROFILES`, `VALID_STATUSES` already in `monsters.py`.
- Produces:
  ```python
  class CreateEntryRequest(BaseModel):
      product_id: int
      name: str
      system_profile: str
      page_number: int | None = None
      raw_text: str | None = None
      ac: int | None = None
      hd_dice: str | None = None
      attacks: list[dict] | None = None
      move: str | None = None
      special_abilities: list[str] | None = None
      environments: list[str] | None = None

  async def create_entry(db: DbSession, request: CreateEntryRequest) -> dict
  ```
  Returns the `_entry_to_dict` shape (same as `patch_entry`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_monsters_crud.py`:

```python
"""Tests for hand create / clear-on-patch / delete of bestiary entries."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from grimoire.api.routes.monsters import (
    CreateEntryRequest,
    create_entry,
)
from grimoire.models import MonsterEntry, Product


async def make_product(db, path):
    product = Product(file_path=path, file_name=path.rsplit("/", 1)[-1],
                      file_size=1, file_hash=path, title="Test Bestiary",
                      text_extracted=True, extracted_text_path="/t/x.json")
    db.add(product)
    await db.flush()
    return product


async def test_create_happy_path(db):
    product = await make_product(db, "/t/crud-create-1.pdf")
    result = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Giant Clam", system_profile="dcc",
        page_number=109, ac=26, hd_dice="5d6", move="0'",
        attacks=[], special_abilities=[], environments=["aquatic"],
        raw_text="source excerpt",
    ))
    assert result["name"] == "Giant Clam"
    assert result["product_id"] == product.id
    assert result["page_number"] == 109
    assert result["ac"] == 26
    assert result["move"] == "0'"
    assert result["environments"] == ["aquatic"]
    assert result["raw_text"] == "source excerpt"

    stored = (await db.execute(
        select(MonsterEntry).where(MonsterEntry.id == result["id"])
    )).scalar_one()
    assert stored.name == "Giant Clam"


async def test_create_derives_stats_like_extraction(db):
    product = await make_product(db, "/t/crud-create-2.pdf")
    result = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Cone Snail", system_profile="dcc",
        hd_dice="3d6",
        attacks=[{"name": "sting", "bonus": 2, "damage_dice": "1d4"}],
    ))
    assert result["hp_avg"] == 10.5
    assert result["hd_value"] == 3.0
    assert result["attacks"][0]["damage_avg"] == 2.5
    assert result["flags"] == []


async def test_create_flags_like_extraction(db):
    product = await make_product(db, "/t/crud-create-3.pdf")
    result = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Blob", system_profile="dcc", hd_dice="2d8",
    ))
    assert result["flags"] == ["no_attacks"]


async def test_create_is_confirmed_with_null_confidence(db):
    product = await make_product(db, "/t/crud-create-4.pdf")
    result = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Hand Typed", system_profile="dcc",
    ))
    assert result["review_status"] == "confirmed"
    assert result["extraction_confidence"] is None


async def test_create_rejects_unknown_product(db):
    with pytest.raises(HTTPException) as exc:
        await create_entry(db=db, request=CreateEntryRequest(
            product_id=999999, name="Ghost", system_profile="dcc",
        ))
    assert exc.value.status_code == 404


async def test_create_rejects_unknown_profile(db):
    product = await make_product(db, "/t/crud-create-5.pdf")
    with pytest.raises(HTTPException) as exc:
        await create_entry(db=db, request=CreateEntryRequest(
            product_id=product.id, name="Ghost", system_profile="pathfinder",
        ))
    assert exc.value.status_code == 400


async def test_create_rejects_blank_name(db):
    product = await make_product(db, "/t/crud-create-6.pdf")
    with pytest.raises(HTTPException) as exc:
        await create_entry(db=db, request=CreateEntryRequest(
            product_id=product.id, name="   ", system_profile="dcc",
        ))
    assert exc.value.status_code == 422


async def test_create_defaults_raw_text_to_empty_string(db):
    product = await make_product(db, "/t/crud-create-7.pdf")
    result = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="No Source", system_profile="dcc",
    ))
    # raw_text is NOT NULL in the model; an omitted excerpt stores "".
    assert result["raw_text"] == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_monsters_crud.py -q`
Expected: collection error — `ImportError: cannot import name 'CreateEntryRequest'`

- [ ] **Step 3: Implement the route**

In `backend/grimoire/api/routes/monsters.py`, add the import near the other `grimoire` imports:

```python
from grimoire.services.monster_fields import derive_stats
```

Add this request model directly after `class PatchEntryRequest` (around line 37):

```python
class CreateEntryRequest(BaseModel):
    product_id: int
    name: str
    system_profile: str
    page_number: int | None = None
    raw_text: str | None = None
    ac: int | None = None
    hd_dice: str | None = None
    attacks: list[dict] | None = None
    move: str | None = None
    special_abilities: list[str] | None = None
    environments: list[str] | None = None
```

Add the route **before** `@router.patch("/{entry_id}")` (the literal-path-first rule does not apply to `POST ""` vs `PATCH /{id}`, but keeping all the `/{entry_id}` routes grouped at the bottom of the file is this module's existing shape):

```python
@router.post("")
async def create_entry(db: DbSession, request: CreateEntryRequest) -> dict:
    """Create a bestiary entry by hand.

    Deriving hd_value/hp_avg/damage_avg server-side (rather than trusting the
    client) is what keeps a typed-in entry indistinguishable from an extracted
    one in the metrics layer.

    extraction_confidence stays null — these are transcribed, not model output,
    and a fabricated score would misrepresent them. Consequence: the "select all
    unflagged" control requires confidence >= 0.8, so hand-created entries are
    never swept up by it. review_status is "confirmed" because a human authored
    the row, which is the scrutiny the review gate exists to apply.
    """
    if request.system_profile not in PROFILES:
        raise HTTPException(status_code=400, detail=f"Unknown system profile: {request.system_profile}")
    if not request.name or not request.name.strip():
        raise HTTPException(status_code=422, detail="name is required")

    result = await db.execute(select(Product).where(Product.id == request.product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    stats, flags = derive_stats(
        ac=request.ac, hd_dice=request.hd_dice, attacks=request.attacks
    )

    entry = MonsterEntry(
        product_id=request.product_id,
        name=request.name.strip(),
        page_number=request.page_number,
        system_profile=request.system_profile,
        # raw_text is NOT NULL; an entry typed from scratch has no source excerpt.
        raw_text=request.raw_text or "",
        ac=stats["ac"],
        hd_dice=stats["hd_dice"],
        hd_value=stats["hd_value"],
        hp_avg=stats["hp_avg"],
        attacks=json.dumps(stats["attacks"]),
        move=request.move,
        special_abilities=json.dumps(request.special_abilities or []),
        environments=json.dumps(request.environments or []),
        extraction_confidence=None,
        flags=json.dumps(flags),
        review_status="confirmed",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _entry_to_dict(entry, product.title)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_monsters_crud.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/api/routes/monsters.py backend/tests/test_monsters_crud.py
git commit -m "feat(bestiary): POST /monsters creates a hand-authored entry"
```

---

## Task 3: `PATCH` distinguishes absent from explicitly null

**Files:**
- Modify: `backend/grimoire/api/routes/monsters.py:363-402` (`patch_entry`)
- Modify: `backend/tests/test_monsters_crud.py` (append)

**Interfaces:**
- Consumes: `CreateEntryRequest` / `create_entry` from Task 2 (tests reuse them for setup); `derive_stats` from Task 1.
- Produces: `patch_entry` unchanged in signature — `async def patch_entry(db: DbSession, entry_id: int, request: PatchEntryRequest) -> dict`. New semantics: a field present in `request.model_fields_set` is applied even when `None`; a field absent is untouched.

**Before you start:** verify the risk the spec calls out. Run:

```bash
git grep -n "patchMonster" frontend/src
```

Every call site must send single non-null keys (`{ name }`, `{ ac }`, `{ hd_dice }`, `{ review_status }`). If any call site spreads a whole entry object or sends explicit nulls today, it would start clearing fields — fix that call site in this task. As of writing, the only caller is `frontend/src/pages/Bestiary.tsx` and all four of its patches are single non-null keys.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_monsters_crud.py` — and extend the import at the top of that file to:

```python
from grimoire.api.routes.monsters import (
    CreateEntryRequest,
    PatchEntryRequest,
    create_entry,
    patch_entry,
)
```

Tests to append:

```python
async def test_patch_clears_field_when_null_sent_explicitly(db):
    product = await make_product(db, "/t/crud-patch-1.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Clearable", system_profile="dcc",
        ac=13, hd_dice="1d8", move="30'",
    ))
    assert created["ac"] == 13

    result = await patch_entry(
        db=db, entry_id=created["id"],
        # model_validate on an explicit dict is what marks `ac` as "set"
        request=PatchEntryRequest.model_validate({"ac": None}),
    )
    assert result["ac"] is None
    # Untouched fields survive
    assert result["hd_dice"] == "1d8"
    assert result["move"] == "30'"


async def test_patch_leaves_absent_fields_alone(db):
    product = await make_product(db, "/t/crud-patch-2.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Untouched", system_profile="dcc",
        ac=13, hd_dice="1d8", move="30'", environments=["forest"],
    ))
    result = await patch_entry(
        db=db, entry_id=created["id"],
        request=PatchEntryRequest.model_validate({"name": "Renamed"}),
    )
    assert result["name"] == "Renamed"
    assert result["ac"] == 13
    assert result["hd_dice"] == "1d8"
    assert result["move"] == "30'"
    assert result["environments"] == ["forest"]


async def test_patch_clearing_hd_clears_derived_fields(db):
    product = await make_product(db, "/t/crud-patch-3.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Dice Gone", system_profile="dcc", hd_dice="3d6",
    ))
    assert created["hp_avg"] == 10.5

    result = await patch_entry(
        db=db, entry_id=created["id"],
        request=PatchEntryRequest.model_validate({"hd_dice": None}),
    )
    assert result["hd_dice"] is None
    assert result["hp_avg"] is None
    assert result["hd_value"] is None


async def test_patch_recomputes_flags(db):
    product = await make_product(db, "/t/crud-patch-4.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Flagged", system_profile="dcc", hd_dice="1d8",
    ))
    assert created["flags"] == ["no_attacks"]

    result = await patch_entry(
        db=db, entry_id=created["id"],
        request=PatchEntryRequest.model_validate({
            "attacks": [{"name": "bite", "bonus": 1, "damage_dice": "1d6"}],
        }),
    )
    assert result["flags"] == []
    assert result["attacks"][0]["damage_avg"] == 3.5


async def test_patch_rejects_explicit_null_review_status(db):
    product = await make_product(db, "/t/crud-patch-5.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Status Guard", system_profile="dcc",
    ))
    with pytest.raises(HTTPException) as exc:
        await patch_entry(
            db=db, entry_id=created["id"],
            request=PatchEntryRequest.model_validate({"review_status": None}),
        )
    assert exc.value.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_monsters_crud.py -q -k patch`
Expected: FAIL — `test_patch_clears_field_when_null_sent_explicitly` asserts `result["ac"] is None` but gets `13`, because the current code skips `None` values.

- [ ] **Step 3: Rewrite `patch_entry`**

Replace the whole `patch_entry` function body in `backend/grimoire/api/routes/monsters.py` with:

```python
@router.patch("/{entry_id}")
async def patch_entry(db: DbSession, entry_id: int, request: PatchEntryRequest) -> dict:
    """Edit an entry; recompute derived fields when their sources change.

    Uses model_fields_set rather than `is not None` so an explicitly-sent null
    clears a field. Without it there is no way to express "this monster has no
    AC" — absent and null were indistinguishable. Callers that omit a key still
    leave it alone, which is what the inline single-key editors rely on.
    """
    result = await db.execute(select(MonsterEntry).where(MonsterEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    sent = request.model_fields_set

    if "review_status" in sent:
        if request.review_status not in VALID_STATUSES:
            raise HTTPException(status_code=422, detail=f"review_status must be one of {sorted(VALID_STATUSES)}")
        entry.review_status = request.review_status

    if "name" in sent:
        if not request.name or not request.name.strip():
            raise HTTPException(status_code=422, detail="name cannot be blank")
        entry.name = request.name.strip()

    for field in ("page_number", "move"):
        if field in sent:
            setattr(entry, field, getattr(request, field))

    if "special_abilities" in sent:
        entry.special_abilities = json.dumps(request.special_abilities or [])
    if "environments" in sent:
        entry.environments = json.dumps(request.environments or [])

    # ac / hd_dice / attacks all feed derive_stats, and flags are a function of
    # all three together — so recompute from the merged post-patch values
    # whenever any one of them was sent, never from the patch alone.
    if sent & {"ac", "hd_dice", "attacks"}:
        stats, flags = derive_stats(
            ac=request.ac if "ac" in sent else entry.ac,
            hd_dice=request.hd_dice if "hd_dice" in sent else entry.hd_dice,
            attacks=(
                request.attacks if "attacks" in sent
                else (json.loads(entry.attacks) if entry.attacks else [])
            ),
        )
        entry.ac = stats["ac"]
        entry.hd_dice = stats["hd_dice"]
        entry.hd_value = stats["hd_value"]
        entry.hp_avg = stats["hp_avg"]
        entry.attacks = json.dumps(stats["attacks"])
        entry.flags = json.dumps(flags)

    await db.commit()
    await db.refresh(entry)
    return _entry_to_dict(entry)
```

Note: `dice_average` and `parse_dice` are no longer used in `monsters.py` after this change — drop them from the import line, leaving `from grimoire.utils.dice import ...` removed entirely if nothing else in the file uses it. Check with `git grep -n "dice_average\|parse_dice" backend/grimoire/api/routes/monsters.py` after editing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_monsters_crud.py -q`
Expected: `13 passed`

- [ ] **Step 5: Verify no regression in the existing PATCH tests**

Run: `cd backend && python -m pytest tests/test_monsters_api.py tests/test_monsters_bulk.py tests/test_monsters_books.py tests/test_monsters_favorites.py tests/test_monsters_guard.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/api/routes/monsters.py backend/tests/test_monsters_crud.py
git commit -m "feat(bestiary): PATCH clears a field when null is sent explicitly"
```

---

## Task 4: `DELETE /api/v1/monsters/{entry_id}`

**Files:**
- Modify: `backend/grimoire/api/routes/monsters.py`
- Modify: `backend/tests/test_monsters_crud.py` (append)

**Interfaces:**
- Produces: `async def delete_entry(db: DbSession, entry_id: int) -> dict` returning `{"deleted": True}`, raising `HTTPException(404)` when the id is unknown.

- [ ] **Step 1: Write the failing tests**

Extend the import at the top of `backend/tests/test_monsters_crud.py` to include `delete_entry`:

```python
from grimoire.api.routes.monsters import (
    CreateEntryRequest,
    PatchEntryRequest,
    create_entry,
    delete_entry,
    patch_entry,
)
```

Append:

```python
async def test_delete_removes_the_row(db):
    product = await make_product(db, "/t/crud-delete-1.pdf")
    created = await create_entry(db=db, request=CreateEntryRequest(
        product_id=product.id, name="Mistake", system_profile="dcc",
    ))
    result = await delete_entry(db=db, entry_id=created["id"])
    assert result == {"deleted": True}

    gone = (await db.execute(
        select(MonsterEntry).where(MonsterEntry.id == created["id"])
    )).scalar_one_or_none()
    assert gone is None


async def test_delete_unknown_id_is_404(db):
    with pytest.raises(HTTPException) as exc:
        await delete_entry(db=db, entry_id=999999)
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_monsters_crud.py -q -k delete`
Expected: collection error — `ImportError: cannot import name 'delete_entry'`

- [ ] **Step 3: Implement the route**

Add to `backend/grimoire/api/routes/monsters.py`, after `patch_entry` and before `get_entry_metrics`:

```python
@router.delete("/{entry_id}")
async def delete_entry(db: DbSession, entry_id: int) -> dict:
    """Remove an entry outright.

    Distinct from rejecting: reject records a judgement about the source
    ("this is not a monster") and is reversible; delete removes a row that
    should never have existed, such as a mistyped duplicate.
    """
    result = await db.execute(select(MonsterEntry).where(MonsterEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    await db.delete(entry)
    await db.commit()
    return {"deleted": True}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_monsters_crud.py -q`
Expected: `15 passed`

- [ ] **Step 5: Run the whole backend suite against the baseline**

Run: `cd backend && python -m pytest -q 2>&1 | tail -10`
Expected: `6 failed, 361 passed` — the same 6 pre-existing failures listed in Global Constraints, and 361 = 346 baseline + 6 (Task 1) + 15 (Tasks 2-4) − 6 ... **do not compute this; just confirm the failure count is still exactly 6 and the six names match.**

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/api/routes/monsters.py backend/tests/test_monsters_crud.py
git commit -m "feat(bestiary): DELETE /monsters/{id} removes an entry"
```

---

## Task 5: Frontend API client + entry form modal

**Files:**
- Modify: `frontend/src/api/monsters.ts`
- Create: `frontend/src/components/MonsterEntryModal.tsx`

**Interfaces:**
- Consumes: `POST /monsters`, `DELETE /monsters/{id}`, `PATCH /monsters/{id}` from Tasks 2-4; `getProducts` from `frontend/src/api/products.ts`.
- Produces:
  ```ts
  export interface MonsterEntryInput {
    product_id: number; name: string; system_profile: string;
    page_number?: number | null; raw_text?: string | null;
    ac?: number | null; hd_dice?: string | null;
    attacks?: { name: string; bonus: number | null; damage_dice: string | null }[];
    move?: string | null; special_abilities?: string[]; environments?: string[];
  }
  export async function createMonster(input: MonsterEntryInput): Promise<MonsterEntry>
  export async function deleteMonster(entryId: number): Promise<void>

  // MonsterEntryModal.tsx
  export type EntryModalMode = 'create' | 'edit' | 'duplicate';
  export interface MonsterEntryModalProps {
    mode: EntryModalMode;
    entry: MonsterEntry | null;       // required for edit/duplicate, null for create
    onClose: () => void;
    onCreated: (entry: MonsterEntry) => void;  // fired only for create/duplicate
    onSaved: () => void;                       // fired only for edit
  }
  export function MonsterEntryModal(props: MonsterEntryModalProps): JSX.Element
  ```

- [ ] **Step 1: Add the API functions**

Append to `frontend/src/api/monsters.ts`:

```ts
export interface MonsterAttackInput {
  name: string;
  bonus: number | null;
  damage_dice: string | null;
}

export interface MonsterEntryInput {
  product_id: number;
  name: string;
  system_profile: string;
  page_number?: number | null;
  raw_text?: string | null;
  ac?: number | null;
  hd_dice?: string | null;
  attacks?: MonsterAttackInput[];
  move?: string | null;
  special_abilities?: string[];
  environments?: string[];
}

export async function createMonster(input: MonsterEntryInput) {
  const { data } = await api.post<MonsterEntry>('/monsters', input);
  return data;
}

export async function deleteMonster(entryId: number) {
  await api.delete(`/monsters/${entryId}`);
}
```

Also update the `patchMonster` signature so an explicit null typechecks — replace the existing function with:

```ts
// Partial<MonsterEntryInput> rather than Partial<MonsterEntry>: derived fields
// (hd_value, hp_avg, damage_avg, flags) are server-computed and must never be
// sent. A key present with value null now clears that field server-side.
export async function patchMonster(
  entryId: number,
  patch: Partial<MonsterEntryInput> & { review_status?: string },
) {
  const { data } = await api.patch<MonsterEntry>(`/monsters/${entryId}`, patch);
  return data;
}
```

- [ ] **Step 2: Verify the client still compiles**

Run: `cd frontend && npx tsc -b`
Expected: errors in `Bestiary.tsx` are acceptable *only* if they are about `patchMutation`'s `Partial<MonsterEntry>` type — if so, widen the local mutation type in Task 6. If `tsc -b` is clean, even better. Note any errors and carry them to Task 6.

- [ ] **Step 3: Write the modal**

Create `frontend/src/components/MonsterEntryModal.tsx`:

```tsx
import { useState } from 'react';
import { X } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createMonster, patchMonster,
  type MonsterEntry, type MonsterAttackInput, type MonsterEntryInput,
} from '../api/monsters';
import { getProducts } from '../api/products';

export type EntryModalMode = 'create' | 'edit' | 'duplicate';

export interface MonsterEntryModalProps {
  mode: EntryModalMode;
  entry: MonsterEntry | null;
  onClose: () => void;
  onCreated: (entry: MonsterEntry) => void;
  onSaved: () => void;
}

const PROFILE_OPTIONS = [
  { value: 'dcc', label: 'DCC' },
  { value: 'osr', label: 'Generic OSR' },
];

interface FormState {
  productId: number | null;
  productLabel: string;
  systemProfile: string;
  name: string;
  pageNumber: string;
  ac: string;
  hdDice: string;
  move: string;
  attacks: MonsterAttackInput[];
  specialAbilities: string;
  environments: string;
  rawText: string;
}

function initialState(mode: EntryModalMode, entry: MonsterEntry | null): FormState {
  if (mode === 'create' || !entry) {
    return {
      productId: null, productLabel: '', systemProfile: 'dcc', name: '',
      pageNumber: '', ac: '', hdDice: '', move: '', attacks: [],
      specialAbilities: '', environments: '', rawText: '',
    };
  }
  const shared = {
    productId: entry.product_id,
    productLabel: entry.product_title ?? `Book ${entry.product_id}`,
    systemProfile: entry.system_profile,
    pageNumber: entry.page_number === null ? '' : String(entry.page_number),
    rawText: entry.raw_text,
  };
  if (mode === 'duplicate') {
    // Book, page, profile and raw_text carry over — that shared context is the
    // whole point of duplicating. Stats are cleared because a split entry's
    // numbers belong to a different creature. The " (copy)" suffix makes an
    // unedited save obvious in the list.
    return {
      ...shared,
      name: `${entry.name} (copy)`,
      ac: '', hdDice: '', move: '', attacks: [],
      specialAbilities: '', environments: '',
    };
  }
  return {
    ...shared,
    name: entry.name,
    ac: entry.ac === null ? '' : String(entry.ac),
    hdDice: entry.hd_dice ?? '',
    move: entry.move ?? '',
    attacks: entry.attacks.map((a) => ({
      name: a.name, bonus: a.bonus, damage_dice: a.damage_dice,
    })),
    specialAbilities: entry.special_abilities.join('\n'),
    environments: entry.environments.join(', '),
  };
}

// '' means "clear this field", not "0". Number('') is 0, which would silently
// write AC 0 — the bug the old inline editor worked around by refusing blanks.
function numOrNull(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === '') return null;
  const parsed = Number(trimmed);
  return Number.isNaN(parsed) ? null : parsed;
}

function strOrNull(raw: string): string | null {
  const trimmed = raw.trim();
  return trimmed === '' ? null : trimmed;
}

function splitList(raw: string, separator: RegExp): string[] {
  return raw.split(separator).map((s) => s.trim()).filter((s) => s.length > 0);
}

const inputClass = 'px-2 py-1 rounded border bg-transparent';
const borderStyle = { borderColor: 'var(--color-border)' };

export function MonsterEntryModal({
  mode, entry, onClose, onCreated, onSaved,
}: MonsterEntryModalProps) {
  const [form, setForm] = useState<FormState>(() => initialState(mode, entry));
  const [bookSearch, setBookSearch] = useState('');
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  // search_mode 'name': the user is naming a book, not searching its contents.
  // Deliberately NOT /monsters/books — creating the first entry for a book is a
  // valid case, and that endpoint only lists books that already have entries.
  const { data: bookResults } = useQuery({
    queryKey: ['entry-modal-book-search', bookSearch],
    queryFn: () => getProducts({ search: bookSearch, search_mode: 'name', per_page: 10 }),
    enabled: bookSearch.trim().length >= 2,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['monsters'] });
    queryClient.invalidateQueries({ queryKey: ['monster-books'] });
    queryClient.invalidateQueries({ queryKey: ['monster-environments'] });
    queryClient.invalidateQueries({ queryKey: ['monster-metrics'] });
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload: MonsterEntryInput = {
        product_id: form.productId!,
        name: form.name.trim(),
        system_profile: form.systemProfile,
        page_number: numOrNull(form.pageNumber),
        ac: numOrNull(form.ac),
        hd_dice: strOrNull(form.hdDice),
        move: strOrNull(form.move),
        attacks: form.attacks.map((a) => ({
          name: a.name.trim() || 'attack',
          bonus: a.bonus,
          damage_dice: a.damage_dice,
        })),
        special_abilities: splitList(form.specialAbilities, /\n/),
        environments: splitList(form.environments, /,/),
      };
      if (mode === 'edit' && entry) {
        // raw_text and system_profile are not editable: raw_text is provenance,
        // and system_profile selects the armor tiers the metrics are computed
        // against, so changing it would silently invalidate every shown number.
        const { product_id, system_profile, raw_text, ...editable } = payload;
        return patchMonster(entry.id, editable);
      }
      return createMonster({ ...payload, raw_text: form.rawText || null });
    },
    onSuccess: (result) => {
      invalidate();
      if (mode === 'edit') onSaved();
      else onCreated(result as MonsterEntry);
    },
    onError: (err: any) =>
      setError(err?.response?.data?.detail ?? 'Failed to save entry'),
  });

  const submit = () => {
    setError(null);
    if (!form.name.trim()) { setError('Name is required'); return; }
    if (mode !== 'edit' && form.productId === null) { setError('Pick a book'); return; }
    saveMutation.mutate();
  };

  const addAttack = () =>
    set('attacks', [...form.attacks, { name: '', bonus: null, damage_dice: null }]);
  const removeAttack = (index: number) =>
    set('attacks', form.attacks.filter((_, i) => i !== index));
  const updateAttack = (index: number, patch: Partial<MonsterAttackInput>) =>
    set('attacks', form.attacks.map((a, i) => (i === index ? { ...a, ...patch } : a)));

  const title = mode === 'create' ? 'Add entry'
    : mode === 'duplicate' ? 'Duplicate entry' : 'Edit entry';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50" />
      <div
        className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-lg shadow-2xl p-4"
        style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)',
                 color: 'var(--color-text-primary)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>

        {mode === 'edit' ? (
          <p className="text-sm opacity-70 mb-3">
            {form.productLabel} · {PROFILE_OPTIONS.find((p) => p.value === form.systemProfile)?.label
              ?? form.systemProfile}
          </p>
        ) : (
          <div className="mb-3 space-y-1">
            <label className="block text-sm opacity-80">Book</label>
            {form.productId !== null ? (
              <div className="flex items-center gap-2 text-sm">
                <span>{form.productLabel}</span>
                <button className="opacity-70 underline"
                  onClick={() => { set('productId', null); set('productLabel', ''); }}>
                  change
                </button>
              </div>
            ) : (
              <>
                <input className={`${inputClass} w-full`} style={borderStyle}
                  placeholder="Search your library… (min 2 chars)"
                  value={bookSearch} onChange={(e) => setBookSearch(e.target.value)} />
                {(bookResults?.items ?? []).map((p) => (
                  <button key={p.id}
                    className="block w-full text-left text-sm px-2 py-1 rounded hover:opacity-80"
                    onClick={() => {
                      set('productId', p.id);
                      set('productLabel', p.title ?? p.file_name);
                    }}>
                    {p.title ?? p.file_name}
                  </button>
                ))}
              </>
            )}
            <div className="flex gap-2 items-center pt-1">
              <label className="text-sm opacity-80">System</label>
              <select className={inputClass} style={borderStyle} value={form.systemProfile}
                onChange={(e) => set('systemProfile', e.target.value)}>
                {PROFILE_OPTIONS.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="text-sm">Name
            <input className={`${inputClass} w-full`} style={borderStyle}
              value={form.name} onChange={(e) => set('name', e.target.value)} />
          </label>
          <label className="text-sm">Page
            <input type="number" className={`${inputClass} w-full`} style={borderStyle}
              value={form.pageNumber} onChange={(e) => set('pageNumber', e.target.value)} />
          </label>
          <label className="text-sm">AC
            <input type="number" className={`${inputClass} w-full`} style={borderStyle}
              value={form.ac} onChange={(e) => set('ac', e.target.value)} />
          </label>
          <label className="text-sm">HD
            <input className={`${inputClass} w-full`} style={borderStyle} placeholder="3d8+3"
              value={form.hdDice} onChange={(e) => set('hdDice', e.target.value)} />
          </label>
          <label className="text-sm col-span-2">Move
            <input className={`${inputClass} w-full`} style={borderStyle} placeholder="30'"
              value={form.move} onChange={(e) => set('move', e.target.value)} />
          </label>
        </div>

        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm opacity-80">Attacks</span>
            <button className="text-sm px-2 py-0.5 rounded border" style={borderStyle}
              onClick={addAttack}>Add attack</button>
          </div>
          {form.attacks.length === 0 && (
            <p className="text-xs opacity-60">No attacks — the entry will be flagged “no_attacks”.</p>
          )}
          {form.attacks.map((atk, i) => (
            <div key={i} className="flex gap-2 items-center mb-1">
              <input className={`${inputClass} flex-1`} style={borderStyle} placeholder="claw"
                value={atk.name} onChange={(e) => updateAttack(i, { name: e.target.value })} />
              <input type="number" className={`${inputClass} w-20`} style={borderStyle}
                placeholder="+bonus"
                value={atk.bonus === null ? '' : String(atk.bonus)}
                onChange={(e) => updateAttack(i, { bonus: numOrNull(e.target.value) })} />
              <input className={`${inputClass} w-40`} style={borderStyle} placeholder="1d4"
                value={atk.damage_dice ?? ''}
                onChange={(e) => updateAttack(i, { damage_dice: strOrNull(e.target.value) })} />
              <button className="opacity-60 px-1" aria-label="Remove attack"
                onClick={() => removeAttack(i)}>×</button>
            </div>
          ))}
          <p className="text-xs opacity-60">
            Freeform damage such as “1d3 plus stun” is fine — it just yields no average.
          </p>
        </div>

        <label className="block text-sm mb-3">Special abilities (one per line)
          <textarea className={`${inputClass} w-full h-20`} style={borderStyle}
            value={form.specialAbilities}
            onChange={(e) => set('specialAbilities', e.target.value)} />
        </label>

        <label className="block text-sm mb-3">Environments (comma separated)
          <input className={`${inputClass} w-full`} style={borderStyle} placeholder="forest, swamp"
            value={form.environments} onChange={(e) => set('environments', e.target.value)} />
        </label>

        {mode !== 'edit' && (
          <label className="block text-sm mb-3">Source excerpt (optional)
            <textarea className={`${inputClass} w-full h-24 font-mono text-xs`} style={borderStyle}
              value={form.rawText} onChange={(e) => set('rawText', e.target.value)} />
          </label>
        )}

        {error && <p className="text-sm mb-2" style={{ color: 'var(--color-danger)' }}>{error}</p>}

        <div className="flex gap-2 justify-end">
          <button className="px-3 py-1 rounded border opacity-80" style={borderStyle}
            onClick={onClose}>Cancel</button>
          <button className="px-3 py-1 rounded border" style={borderStyle}
            disabled={saveMutation.isPending} onClick={submit}>
            {saveMutation.isPending ? 'Saving…' : mode === 'edit' ? 'Save changes' : 'Create entry'}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b`
Expected: no errors originating in `MonsterEntryModal.tsx` or `api/monsters.ts`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/monsters.ts frontend/src/components/MonsterEntryModal.tsx
git commit -m "feat(bestiary): entry form modal + create/delete API client"
```

---

## Task 6: Wire the modal into the Bestiary page

**Files:**
- Modify: `frontend/src/pages/Bestiary.tsx`

**Interfaces:**
- Consumes: `MonsterEntryModal`, `EntryModalMode` from Task 5; `deleteMonster` from Task 5.

- [ ] **Step 1: Add imports and modal state**

In `frontend/src/pages/Bestiary.tsx`, extend the `../api/monsters` import to include `deleteMonster`, and add the modal import:

```tsx
import {
  listMonsters, listEnvironments, getMetrics, patchMonster, rollRandom, queueExtraction,
  bulkSetStatus, listBooks, listFavorites, createFavorite, deleteFavorite, deleteMonster,
  type MonsterEntry, type MonsterFilters, type MonsterEntryInput,
  type BestiaryFavorite, type FavoriteConfig,
} from '../api/monsters';
import { MonsterEntryModal, type EntryModalMode } from '../components/MonsterEntryModal';
```

Add state next to the other `useState` calls (after `const [selectedIds, ...]`):

```tsx
  const [entryModal, setEntryModal] = useState<
    { mode: EntryModalMode; entry: MonsterEntry | null } | null
  >(null);
  const [createdNotice, setCreatedNotice] = useState<MonsterEntry | null>(null);
```

- [ ] **Step 2: Fix the patch mutation type and add the delete mutation**

Replace the existing `patchMutation` declaration's type parameter so explicit nulls typecheck, and add a delete mutation right after it:

```tsx
  const patchMutation = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<MonsterEntryInput> & { review_status?: string } }) =>
      patchMonster(id, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['monsters'] });
      queryClient.invalidateQueries({ queryKey: ['monster-metrics'] });
    },
  });
  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteMonster(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['monsters'] });
      queryClient.invalidateQueries({ queryKey: ['monster-books'] });
    },
  });
```

- [ ] **Step 3: Add the "Add entry" button to the header**

Replace the header block (currently the `<div className="flex items-center justify-between mb-4">` containing the h1 and the Extract button) with:

```tsx
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">Bestiary</h1>
        <div className="flex gap-2">
          <button className="px-3 py-1.5 rounded border" style={{ borderColor: 'var(--color-border)' }}
            onClick={() => setEntryModal({ mode: 'create', entry: null })}>
            Add entry
          </button>
          <button className="px-3 py-1.5 rounded border" style={{ borderColor: 'var(--color-border)' }}
            onClick={() => { setShowExtract(!showExtract); setExtractMessage(null); }}>
            Extract from book…
          </button>
        </div>
      </div>
```

- [ ] **Step 4: Add the post-create notice**

Insert this immediately after that header block, before the `{showExtract && (` block:

```tsx
      {createdNotice && (
        <div className="mb-4 p-3 rounded border flex items-center gap-3 text-sm"
          style={{ borderColor: 'var(--color-border)' }}>
          {/* A created entry is confirmed, so it is invisible while the list is
              filtered to pending — say so and offer the switch rather than
              letting the user conclude the save failed. */}
          <span>
            Created “{createdNotice.name}” as <strong>confirmed</strong>.
            {reviewMode && ' It is not shown in the pending list.'}
          </span>
          {reviewMode && (
            <button className="px-2 py-0.5 rounded border" style={{ borderColor: 'var(--color-border)' }}
              onClick={() => {
                setFilter({ review_status: 'confirmed', q: createdNotice.name });
                setCreatedNotice(null);
              }}>
              Show it
            </button>
          )}
          <button className="ml-auto opacity-60" onClick={() => setCreatedNotice(null)}>×</button>
        </div>
      )}
```

Note: `reviewMode` and `setFilter` are declared later in the component body than the JSX return, which is fine — `const reviewMode = ...` is evaluated before `return`. No reordering needed.

- [ ] **Step 5: Add per-row Edit / Duplicate / Delete**

In the entry row, the stat cluster on the right currently reads:

```tsx
              <div className="text-sm opacity-80 flex gap-3">
                <span>AC {entry.ac ?? '?'}</span>
```

Add a row-actions cluster immediately after that `</div>` closing the stat cluster (i.e. between it and the closing `</div>` of the flex row):

```tsx
              <div className="flex gap-1 ml-3 text-xs">
                <button className="px-2 py-0.5 rounded border" style={{ borderColor: 'var(--color-border)' }}
                  onClick={() => setEntryModal({ mode: 'edit', entry })}>Edit</button>
                <button className="px-2 py-0.5 rounded border" style={{ borderColor: 'var(--color-border)' }}
                  onClick={() => setEntryModal({ mode: 'duplicate', entry })}>Duplicate</button>
                <button className="px-2 py-0.5 rounded border opacity-70"
                  style={{ borderColor: 'var(--color-border)' }}
                  disabled={deleteMutation.isPending}
                  onClick={() => {
                    if (window.confirm(`Delete “${entry.name}”? This cannot be undone.`)) {
                      deleteMutation.mutate(entry.id);
                    }
                  }}>Delete</button>
              </div>
```

- [ ] **Step 6: Render the modal**

Add just before the final closing `</div>` of the component's returned JSX (after the pagination block):

```tsx
      {entryModal && (
        <MonsterEntryModal
          // Remount per target so the form re-initialises from the new entry
          // rather than keeping the previous one's state.
          key={`${entryModal.mode}-${entryModal.entry?.id ?? 'new'}`}
          mode={entryModal.mode}
          entry={entryModal.entry}
          onClose={() => setEntryModal(null)}
          onSaved={() => setEntryModal(null)}
          onCreated={(created) => { setEntryModal(null); setCreatedNotice(created); }}
        />
      )}
```

- [ ] **Step 7: Typecheck**

Run: `cd frontend && npx tsc -b`
Expected: zero errors (baseline is clean).

- [ ] **Step 8: Full backend suite one more time**

Run: `cd backend && python -m pytest -q 2>&1 | tail -10`
Expected: exactly 6 failures, matching the six pre-existing names in Global Constraints.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/Bestiary.tsx
git commit -m "feat(bestiary): add/edit/duplicate/delete entry controls"
```

---

## Manual verification (after Task 6)

Backend on, frontend on, Bestiary page open:

1. **Add entry** → search a book, pick it, type a name and `3d6` HD, save. Notice appears saying created-and-confirmed. Entry appears in the confirmed list with average HP 10.5 (expand it to check the metrics panel).
2. **Add entry while in Review pending** → notice says it is not shown in the pending list and offers "Show it"; clicking it switches to confirmed filtered to that name.
3. **Edit** an existing entry → clear the AC field entirely and save → the row shows `AC ?` (this is the `model_fields_set` path; before this work it was impossible).
4. **Duplicate** entry #124 (the Cone Snail / Giant Clam merged row, if present) → the form carries book, page, profile and `raw_text`, name reads "… (copy)", stats are blank.
5. **Delete** a throwaway entry → confirm prompt, row disappears, and it stays gone after a refresh.

---

## Spec coverage check

| Spec requirement | Task |
|---|---|
| `POST /api/v1/monsters`, required `product_id`/`name`/`system_profile` | 2 |
| profile validated against `PROFILES` (400), product exists (404) | 2 |
| server derives `hd_value`, `hp_avg`, `damage_avg` with `grimoire.utils.dice` | 1, 2 |
| same validation produces `flags` (`no_attacks` on a hand entry) | 1, 2 |
| `extraction_confidence` null, `review_status` confirmed | 2 |
| UI handles create-while-filtered-to-pending | 6 |
| `PATCH` distinguishes absent from explicit null via `model_fields_set` | 3 |
| editable field list; derived recomputed on source change | 3 |
| `DELETE /api/v1/monsters/{entry_id}` → `{"deleted": true}`, 404 if absent | 4 |
| modal with controlled state (not inline expansion) | 5 |
| Add entry / Edit / Duplicate entry points | 5, 6 |
| duplicate carries book, page, profile, raw_text; clears stats; " (copy)" suffix | 5 |
| attacks as add/remove rows; freeform damage accepted | 5 |
| book picker via `GET /products?search_mode=name`, not `/monsters/books` | 5 |
| grep for existing PATCH callers before changing semantics | 3 (pre-step) |
