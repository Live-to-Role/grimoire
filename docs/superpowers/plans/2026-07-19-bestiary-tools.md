# Bestiary Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract monster entries from owned bestiary PDFs into a reviewed, normalized index, then serve environment-filtered browsing, random encounters, rollable tables, and closed-form combat metrics.

**Architecture:** Hybrid extraction pipeline — heuristic segmentation over already-extracted page-anchored markdown (`get_extracted_pages`) finds candidate entries; an LLM normalizes each candidate into a strict schema (reusing the provider helpers in `processors/structured_extractor.py`); results persist as `MonsterEntry` rows gated by `review_status`. A queue handler (`monster_extract`) runs the pipeline in the existing out-of-process worker. Metrics are pure functions computed on read. Frontend adds a "Bestiary" view (NavRail item + App.tsx branch — this app uses view-state switching, not a router).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, SQLite/aiosqlite, pytest (+asyncio auto mode), React 18 + TypeScript + React Query v5, axios.

**Spec:** `docs/superpowers/specs/2026-07-19-bestiary-tools-design.md` — read it before starting.

## Global Constraints

- Work on branch `feat/bestiary-tools` off `main`.
- Backend tests run from `backend/` with miniconda: `python -m pytest` (NOT `.venv` — it lacks pytest). 7 pre-existing failures are baseline; only new failures matter.
- Frontend gate is `npx tsc -b` from `frontend/` (no frontend test harness).
- Route handlers commit explicitly — `get_db()` does NOT auto-commit.
- The tools' outputs only ever include name/page/book pointers, short derived tags, and computed math — never reproduce stat-block prose, flavor text, or art. Two deliberate exceptions: the review UI shows `raw_text` to the owner, and the browse view lists `special_abilities` as short derived tags under "Special (not in the math)", because damage-per-round alone is actively misleading for save-or-die, level-drain, or similar abilities the math omits.
- Only `review_status == "confirmed"` entries feed browse/random/metrics endpoints.
- LLM calls happen only inside the queue handler (worker process), never inline in API routes.
- New table is created by `Base.metadata.create_all` in `init_db()`/test fixtures automatically — no `_ensure_columns()` entry needed (that's for new columns on existing tables).
- JSON-in-Text columns follow the existing convention (`ProcessingQueue.config`): store with `json.dumps`, read with `json.loads`.
- SQLAlchemy `default=` is DDL-level; Python constructor gives `None` for unset fields — set defaults explicitly when constructing.
- The test `db` fixture rolls back uncommitted work, but the engine is session-scoped — committed rows persist across tests in the same run; use distinct file paths/names per test.

## File Structure

| File | Responsibility |
|---|---|
| `backend/grimoire/utils/dice.py` (create) | Parse dice notation, compute averages |
| `backend/grimoire/processors/system_profiles.py` (create) | DCC + OSR profiles: segmentation anchors, AC/THAC0 normalization, armor tiers, LLM prompt hints |
| `backend/grimoire/models/monster_entry.py` (create) | `MonsterEntry` ORM model |
| `backend/grimoire/models/__init__.py` (modify) | Register model |
| `backend/grimoire/processors/monster_segmenter.py` (create) | Heuristic candidate segmentation over extracted pages |
| `backend/grimoire/processors/monster_normalizer.py` (create) | LLM normalization prompt/call, post-validation, field derivation |
| `backend/grimoire/services/monster_metrics.py` (create) | Closed-form metrics (hit chance vs tiers, DPR) |
| `backend/grimoire/services/queue_processor.py` (modify) | `monster_extract` queue handler |
| `backend/grimoire/api/routes/monsters.py` (create) | Bestiary API endpoints |
| `backend/grimoire/api/routes/__init__.py` (modify) | Register router at `/monsters` |
| `frontend/src/api/monsters.ts` (create) | API client + types |
| `frontend/src/pages/Bestiary.tsx` (create) | Bestiary view: filters, list, metrics, roll/table, review mode |
| `frontend/src/components/NavRail.tsx` (modify) | Add Bestiary nav item |
| `frontend/src/App.tsx` (modify) | Render Bestiary view |
| `backend/tests/test_dice.py`, `test_system_profiles.py`, `test_monster_entry_model.py`, `test_monster_segmenter.py`, `test_monster_normalizer.py`, `test_monster_metrics.py`, `test_monsters_api.py` (create) | Tests per unit |

Existing prototypes `processors/statblock_extractor.py` and `api/routes/structured.py` are left untouched (out of scope); `processors/structured_extractor.py` is reused only for its `extract_with_openai` / `extract_with_anthropic` helpers.

---

### Task 1: Dice utilities

**Files:**
- Create: `backend/grimoire/utils/dice.py`
- Test: `backend/tests/test_dice.py`

**Interfaces:**
- Consumes: nothing
- Produces: `parse_dice(notation: str) -> tuple[int, int, int] | None` (count, sides, modifier; `None` if unparseable), `dice_average(notation: str) -> float | None`. Plain integers like `"7"` parse as `(0, 0, 7)` with average `7.0`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_dice.py
"""Tests for dice notation parsing."""

from grimoire.utils.dice import parse_dice, dice_average


def test_parse_simple():
    assert parse_dice("3d8") == (3, 8, 0)


def test_parse_with_modifier():
    assert parse_dice("3d8+3") == (3, 8, 3)
    assert parse_dice("2d4-1") == (2, 4, -1)


def test_parse_plain_integer():
    assert parse_dice("7") == (0, 0, 7)


def test_parse_whitespace_and_case():
    assert parse_dice(" 1D6 + 2 ") == (1, 6, 2)


def test_parse_garbage_returns_none():
    assert parse_dice("special") is None
    assert parse_dice("") is None
    assert parse_dice(None) is None


def test_average():
    assert dice_average("3d8+3") == 16.5   # 3 * 4.5 + 3
    assert dice_average("1d6") == 3.5
    assert dice_average("7") == 7.0
    assert dice_average("nonsense") is None
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/`: `python -m pytest tests/test_dice.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grimoire.utils.dice'`

- [ ] **Step 3: Write the implementation**

```python
# backend/grimoire/utils/dice.py
"""Dice notation parsing and averaging."""

import re

_DICE_RE = re.compile(r"^\s*(\d+)\s*[dD]\s*(\d+)\s*(?:([+-])\s*(\d+))?\s*$")
_INT_RE = re.compile(r"^\s*(\d+)\s*$")


def parse_dice(notation: str | None) -> tuple[int, int, int] | None:
    """Parse dice notation like '3d8+3' into (count, sides, modifier).

    Plain integers parse as (0, 0, value). Returns None if unparseable.
    """
    if not notation:
        return None
    match = _DICE_RE.match(notation)
    if match:
        count, sides = int(match.group(1)), int(match.group(2))
        modifier = int(match.group(4)) if match.group(4) else 0
        if match.group(3) == "-":
            modifier = -modifier
        return (count, sides, modifier)
    match = _INT_RE.match(notation)
    if match:
        return (0, 0, int(match.group(1)))
    return None


def dice_average(notation: str | None) -> float | None:
    """Average roll of a dice expression, or None if unparseable."""
    parsed = parse_dice(notation)
    if parsed is None:
        return None
    count, sides, modifier = parsed
    return count * (sides + 1) / 2 + modifier
```

- [ ] **Step 4: Run tests to verify they pass**

From `backend/`: `python -m pytest tests/test_dice.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/utils/dice.py backend/tests/test_dice.py
git commit -m "feat(bestiary): dice notation parsing and averaging"
```

---

### Task 2: System profiles

**Files:**
- Create: `backend/grimoire/processors/system_profiles.py`
- Test: `backend/tests/test_system_profiles.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `@dataclass SystemProfile` with fields: `id: str`, `label: str`, `statline_anchor: re.Pattern`, `armor_tiers: dict[str, int]` (ordered: unarmored/leather/chain/plate & shield → ascending AC), `prompt_hint: str`
  - `normalize_thac0(thac0: int) -> int` — attack bonus = `20 - thac0`
  - `normalize_descending_ac(ac: int) -> int` — ascending AC = `19 - ac` (OSE convention: descending 9 ↔ ascending 10)
  - `get_profile(profile_id: str) -> SystemProfile` — raises `KeyError` for unknown ids
  - `PROFILES: dict[str, SystemProfile]` with keys `"dcc"` and `"osr"`

The canonical model is hit probability vs. defense (see spec); these helpers translate input dialects to a normalized ascending-AC attack bonus at extraction time.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_system_profiles.py
"""Tests for system profile normalization and registry."""

import pytest

from grimoire.processors.system_profiles import (
    PROFILES,
    get_profile,
    normalize_descending_ac,
    normalize_thac0,
)


def test_thac0_to_bonus():
    assert normalize_thac0(19) == 1
    assert normalize_thac0(20) == 0
    assert normalize_thac0(15) == 5


def test_descending_ac_to_ascending():
    assert normalize_descending_ac(9) == 10   # unarmored
    assert normalize_descending_ac(7) == 12   # leather
    assert normalize_descending_ac(2) == 17   # plate & shield


def test_profiles_registered():
    assert set(PROFILES.keys()) == {"dcc", "osr"}
    assert get_profile("dcc").label == "Dungeon Crawl Classics"
    with pytest.raises(KeyError):
        get_profile("gurps")


def test_armor_tiers_ascend():
    for profile in PROFILES.values():
        tiers = list(profile.armor_tiers.values())
        assert tiers == sorted(tiers), f"{profile.id} tiers must ascend"
        assert len(tiers) == 4


def test_dcc_anchor_matches_inline_statline():
    line = "Orc: Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; MV 30'; Act 1d20; SV Fort +1, Ref +0, Will -1; AL C."
    assert get_profile("dcc").statline_anchor.search(line)


def test_osr_anchor_matches_block_statline():
    line = "AC 9 [10], HD 1d4, Att 1 x bite (poison), THAC0 19, MV 60' (20')"
    assert get_profile("osr").statline_anchor.search(line)
    assert not get_profile("osr").statline_anchor.search("The cave is dark and damp.")
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/`: `python -m pytest tests/test_system_profiles.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# backend/grimoire/processors/system_profiles.py
"""Game system profiles for monster extraction.

The canonical downstream model is hit probability as a function of target
defense, encoded as a normalized attack bonus vs. ascending AC. THAC0,
attack matrices, and descending AC are input dialects that these profiles
translate at extraction time; they never leak past this layer.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SystemProfile:
    id: str
    label: str
    statline_anchor: re.Pattern
    # Ordered ascending-AC values for: unarmored, leather, chain, plate & shield
    armor_tiers: dict[str, int]
    prompt_hint: str


def normalize_thac0(thac0: int) -> int:
    """THAC0 -> ascending-AC attack bonus."""
    return 20 - thac0


def normalize_descending_ac(ac: int) -> int:
    """Descending AC -> ascending AC (OSE convention: 9 <-> 10)."""
    return 19 - ac


DCC_PROFILE = SystemProfile(
    id="dcc",
    label="Dungeon Crawl Classics",
    # DCC inline statline: "Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; ..."
    statline_anchor=re.compile(r"Init\s+[+-]?\d+.{0,120}?\bAC\s+\d+.{0,80}?\bHD\s+\d+d\d+", re.IGNORECASE | re.DOTALL),
    armor_tiers={"unarmored": 10, "leather": 12, "chain": 15, "plate & shield": 19},
    prompt_hint=(
        "This is a Dungeon Crawl Classics (DCC) stat line. AC is ascending. "
        "Attack bonuses appear like 'Atk bite +4 melee (1d6+2)'. HD like '3d8+3'."
    ),
)

OSR_PROFILE = SystemProfile(
    id="osr",
    label="Generic OSR (B/X, AD&D, OSE-style)",
    # OSR block statline: needs AC and HD near each other; THAC0 optional.
    statline_anchor=re.compile(r"\bAC[:\s]+-?\d+.{0,160}?\bHD[:\s]+\d+", re.IGNORECASE | re.DOTALL),
    armor_tiers={"unarmored": 10, "leather": 12, "chain": 14, "plate & shield": 17},
    prompt_hint=(
        "This is an old-school (B/X, AD&D, OSE) stat block. AC may be DESCENDING "
        "(lower is better, unarmored = 9) unless a bracketed ascending value like "
        "'AC 7 [12]' is present. THAC0 may be given instead of attack bonuses. "
        "Report values exactly as printed and set ac_style accordingly."
    ),
)

PROFILES: dict[str, SystemProfile] = {p.id: p for p in (DCC_PROFILE, OSR_PROFILE)}


def get_profile(profile_id: str) -> SystemProfile:
    return PROFILES[profile_id]
```

- [ ] **Step 4: Run tests to verify they pass**

From `backend/`: `python -m pytest tests/test_system_profiles.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/processors/system_profiles.py backend/tests/test_system_profiles.py
git commit -m "feat(bestiary): DCC and OSR system profiles with AC/THAC0 normalization"
```

---

### Task 3: MonsterEntry model

**Files:**
- Create: `backend/grimoire/models/monster_entry.py`
- Modify: `backend/grimoire/models/__init__.py` (add import + `__all__` entry, matching how other models are registered there)
- Test: `backend/tests/test_monster_entry_model.py`

**Interfaces:**
- Consumes: `grimoire.database.Base`
- Produces: `MonsterEntry` ORM class, table `monster_entries`. JSON-in-Text fields: `attacks` (list of `{name, bonus, damage_dice, damage_avg}`), `special_abilities` (list[str]), `environments` (list[str]), `flags` (list[str]). `review_status` in `pending|confirmed|rejected`. `hd_value: float | None` = numeric dice count from `hd_dice` for range filtering.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_monster_entry_model.py
"""Tests for the MonsterEntry model."""

import json

from sqlalchemy import select

from grimoire.models import MonsterEntry, Product


async def test_create_monster_entry(db):
    product = Product(
        file_path="/t/bestiary-model-test.pdf",
        file_name="bestiary-model-test.pdf",
        file_size=1,
        file_hash="mh1",
    )
    db.add(product)
    await db.flush()

    entry = MonsterEntry(
        product_id=product.id,
        name="Peryton",
        page_number=142,
        system_profile="osr",
        raw_text="PERYTON\nAC 7 [12], HD 4 ...",
        ac=12,
        hd_dice="4d8",
        hd_value=4.0,
        hp_avg=18.0,
        attacks=json.dumps([{"name": "antlers", "bonus": 4, "damage_dice": "2d4", "damage_avg": 5.0}]),
        move="240' flying",
        special_abilities=json.dumps(["heart-eating"]),
        environments=json.dumps(["mountains", "wilderness"]),
        extraction_confidence=0.9,
        flags=json.dumps([]),
        review_status="pending",
    )
    db.add(entry)
    await db.flush()

    result = await db.execute(select(MonsterEntry).where(MonsterEntry.name == "Peryton"))
    saved = result.scalar_one()
    assert saved.product_id == product.id
    assert saved.review_status == "pending"
    assert json.loads(saved.environments) == ["mountains", "wilderness"]
```

- [ ] **Step 2: Run test to verify it fails**

From `backend/`: `python -m pytest tests/test_monster_entry_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'MonsterEntry'`

- [ ] **Step 3: Write the model and register it**

```python
# backend/grimoire/models/monster_entry.py
"""MonsterEntry model - extracted bestiary entries (see bestiary tools spec)."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from grimoire.database import Base


class MonsterEntry(Base):
    """A monster entry extracted from an owned bestiary PDF.

    Only review_status == "confirmed" entries feed the bestiary tools.
    JSON-in-Text fields: attacks, special_abilities, environments, flags.
    """

    __tablename__ = "monster_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    system_profile: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Normalized combatant statline (ascending AC, normalized attack bonuses)
    ac: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hd_dice: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hd_value: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    hp_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    attacks: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    move: Mapped[str | None] = mapped_column(String(100), nullable=True)
    special_abilities: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    environments: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list

    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    flags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of validation problems
    review_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<MonsterEntry(id={self.id}, name='{self.name}', status='{self.review_status}')>"
```

In `backend/grimoire/models/__init__.py`, add (following the file's existing import/`__all__` style):

```python
from grimoire.models.monster_entry import MonsterEntry
```

and add `"MonsterEntry"` to `__all__` if the file maintains one.

- [ ] **Step 4: Run test to verify it passes**

From `backend/`: `python -m pytest tests/test_monster_entry_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/models/monster_entry.py backend/grimoire/models/__init__.py backend/tests/test_monster_entry_model.py
git commit -m "feat(bestiary): MonsterEntry model"
```

---

### Task 4: Heuristic segmenter

**Files:**
- Create: `backend/grimoire/processors/monster_segmenter.py`
- Test: `backend/tests/test_monster_segmenter.py`

**Interfaces:**
- Consumes: `SystemProfile` from Task 2; pages in the `get_extracted_pages()` shape: `[{"page": int, "markdown": str}, ...]`
- Produces: `@dataclass Candidate {name_guess: str, page: int, raw_text: str}`; `segment_pages(pages: list[dict], profile: SystemProfile) -> list[Candidate]`

Strategy (high recall, sloppy precision is fine — LLM + reviewer sit downstream): scan each page's markdown for `profile.statline_anchor` matches. For each match, the candidate block spans from the nearest preceding header-ish line (short line, mostly uppercase or title-case, possibly markdown `#`/`**` markup) to 15 lines past the anchor or the next candidate's header, whichever comes first. `name_guess` is that header line stripped of markdown markup; if no header found within 6 lines above the anchor, use the first 40 chars of the anchor line and still emit the candidate.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_monster_segmenter.py
"""Tests for heuristic monster candidate segmentation."""

from grimoire.processors.monster_segmenter import Candidate, segment_pages
from grimoire.processors.system_profiles import get_profile

DCC_PAGE = """
## Orc

Fierce warriors of the wastes, orcs raid caravans by night.

Orc: Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; MV 30'; Act 1d20;
SV Fort +1, Ref +0, Will -1; AL C.

## Giant Rat

Giant Rat: Init +2; Atk bite +1 melee (1d3); AC 13; HD 1d6; MV 30'; Act 1d20;
SV Fort +2, Ref +2, Will -1; AL N.
"""

OSR_PAGE = """
**PERYTON**

A monstrous winged stag with the shadow of a man. Found in lonely mountains.

AC 7 [12], HD 4, Att 1 x antlers (2d4), THAC0 15, MV 240' (80') flying,
SV D10 W11 P12 B13 S14, ML 9, AL Chaotic, XP 125

The peryton must consume the heart of its victim.
"""

PROSE_PAGE = """
The judge should feel free to add wandering monsters. Consult chapter 4
for guidance on encounter design and terrain.
"""


def test_dcc_segmentation_finds_both_monsters():
    pages = [{"page": 12, "markdown": DCC_PAGE}]
    candidates = segment_pages(pages, get_profile("dcc"))
    names = [c.name_guess for c in candidates]
    assert names == ["Orc", "Giant Rat"]
    assert all(c.page == 12 for c in candidates)
    assert "AC 13" in candidates[0].raw_text
    assert "Giant Rat" not in candidates[0].raw_text


def test_osr_segmentation_finds_peryton_with_prose():
    pages = [{"page": 142, "markdown": OSR_PAGE}]
    candidates = segment_pages(pages, get_profile("osr"))
    assert len(candidates) == 1
    assert candidates[0].name_guess == "PERYTON"
    assert candidates[0].page == 142
    assert "THAC0 15" in candidates[0].raw_text
    assert "consume the heart" in candidates[0].raw_text


def test_prose_page_yields_nothing():
    pages = [{"page": 3, "markdown": PROSE_PAGE}]
    assert segment_pages(pages, get_profile("dcc")) == []
    assert segment_pages(pages, get_profile("osr")) == []


def test_anchor_without_header_still_emits_candidate():
    pages = [{"page": 7, "markdown": "Init +0; Atk bite +2 melee (1d4); AC 12; HD 2d8; MV 20'; Act 1d20; SV Fort +1, Ref +1, Will +0; AL N."}]
    candidates = segment_pages(pages, get_profile("dcc"))
    assert len(candidates) == 1
    assert candidates[0].name_guess  # non-empty fallback
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/`: `python -m pytest tests/test_monster_segmenter.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# backend/grimoire/processors/monster_segmenter.py
"""Heuristic segmentation of extracted bestiary pages into monster candidates.

High recall, sloppy precision: the LLM normalizer and human review gate sit
downstream, so emitting a bad candidate is cheap and missing one is not.
"""

import re
from dataclasses import dataclass

from grimoire.processors.system_profiles import SystemProfile

# A header-ish line: short, not ending in sentence punctuation, either markdown
# heading/bold or mostly capitalized words.
_MARKUP_RE = re.compile(r"^[#*_\s]+|[#*_\s]+$")
_HEADER_RE = re.compile(r"^(?:#{1,4}\s+|\*\*)?[A-Z][A-Za-z'\-]*(?:[\s,][A-Za-z'\-]+){0,5}(?:\*\*)?\s*$")

_MAX_LINES_ABOVE = 6      # how far above the anchor to look for a header
_MAX_LINES_BELOW = 15     # how far below the anchor a block may extend


@dataclass
class Candidate:
    name_guess: str
    page: int
    raw_text: str


def _clean_header(line: str) -> str:
    return _MARKUP_RE.sub("", line).strip()


def _is_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 60 or stripped.endswith((".", ",", ";", ":")):
        return False
    return bool(_HEADER_RE.match(stripped))


def segment_pages(pages: list[dict], profile: SystemProfile) -> list[Candidate]:
    """Find candidate monster entries in page-anchored markdown."""
    candidates: list[Candidate] = []
    for page_dict in pages:
        page_num = page_dict.get("page", 0)
        lines = (page_dict.get("markdown") or "").split("\n")
        text = "\n".join(lines)

        # Map anchor match positions to line indexes
        anchor_lines: list[int] = []
        for match in profile.statline_anchor.finditer(text):
            line_idx = text.count("\n", 0, match.start())
            if not anchor_lines or line_idx > anchor_lines[-1]:
                anchor_lines.append(line_idx)

        # Determine block boundaries per anchor
        starts: list[int] = []
        names: list[str] = []
        for anchor_idx in anchor_lines:
            start = max(0, anchor_idx - _MAX_LINES_ABOVE)
            name = ""
            for i in range(anchor_idx - 1, start - 1, -1):
                if _is_header(lines[i]):
                    start = i
                    name = _clean_header(lines[i])
                    break
            if not name:
                start = anchor_idx
                name = lines[anchor_idx].strip()[:40]
            starts.append(start)
            names.append(name)

        for pos, (start, anchor_idx) in enumerate(zip(starts, anchor_lines)):
            end = min(len(lines), anchor_idx + _MAX_LINES_BELOW)
            if pos + 1 < len(starts):
                end = min(end, starts[pos + 1])
            block = "\n".join(lines[start:end]).strip()
            if block:
                candidates.append(Candidate(name_guess=names[pos], page=page_num, raw_text=block))
    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

From `backend/`: `python -m pytest tests/test_monster_segmenter.py -v`
Expected: 4 PASS. If the DCC test fails on name order or block bleed, adjust `_MAX_LINES_BELOW`/header detection — do not weaken the assertions.

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/processors/monster_segmenter.py backend/tests/test_monster_segmenter.py
git commit -m "feat(bestiary): heuristic candidate segmentation over extracted pages"
```

---

### Task 5: LLM normalizer with validation

**Files:**
- Create: `backend/grimoire/processors/monster_normalizer.py`
- Test: `backend/tests/test_monster_normalizer.py`

**Interfaces:**
- Consumes: `Candidate` (Task 4), `SystemProfile` + normalization fns (Task 2), `dice_average`/`parse_dice` (Task 1), `extract_with_openai` / `extract_with_anthropic` from `grimoire.processors.structured_extractor` (existing: `async (text, prompt_template, api_key, model) -> dict`; the template uses a `{text}` placeholder)
- Produces:
  - `async normalize_candidate(candidate: Candidate, profile: SystemProfile, provider: str | None = None, model: str | None = None) -> dict | None` — returns an entry dict ready for `MonsterEntry(**entry)` minus `product_id` (keys: `name, page_number, system_profile, raw_text, ac, hd_dice, hd_value, hp_avg, attacks, move, special_abilities, environments, extraction_confidence, flags, review_status`), JSON fields already `json.dumps`-ed; returns `None` when no provider key is configured or the LLM says the candidate is not a monster
  - `build_entry_from_llm(llm: dict, candidate: Candidate, profile: SystemProfile) -> dict` — pure function doing normalization + validation (unit-testable without LLM)

LLM output contract (the prompt demands exactly this JSON):

```json
{"is_monster": true, "name": "Orc", "ac": 13, "ac_style": "ascending",
 "thac0": null, "hd_dice": "1d8+1",
 "attacks": [{"name": "claw", "bonus": 1, "damage_dice": "1d4"}],
 "move": "30'", "special_abilities": [], "environments": ["wilderness"],
 "confidence": 0.9}
```

Normalization rules in `build_entry_from_llm`:
- `ac_style == "descending"` → `ac = normalize_descending_ac(ac)`; else use as-is.
- Attack `bonus` missing but top-level `thac0` present → `bonus = normalize_thac0(thac0)`.
- `damage_avg = dice_average(damage_dice)` per attack; `hp_avg = dice_average(hd_dice)` when it parses; `hd_value = float(count)` from `parse_dice(hd_dice)` (for `"1d4"` → 1.0; unparseable → `None`).
- Validation flags (list[str], entry kept, `review_status` stays `"pending"`): `ac` outside 0–30 after normalization → `"ac_out_of_range"`; `hd_dice` present but unparseable → `"hd_unparseable"`; any attack damage unparseable → `"damage_unparseable"`; empty `attacks` → `"no_attacks"`. Flags never auto-confirm or auto-reject — the reviewer decides.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_monster_normalizer.py
"""Tests for LLM output normalization and validation (LLM mocked)."""

import json

import pytest

from grimoire.processors.monster_normalizer import build_entry_from_llm, normalize_candidate
from grimoire.processors.monster_segmenter import Candidate
from grimoire.processors.system_profiles import get_profile


def make_candidate(**kwargs):
    defaults = {"name_guess": "Orc", "page": 12, "raw_text": "Orc: Init +1; ... AC 13; HD 1d8+1"}
    defaults.update(kwargs)
    return Candidate(**defaults)


def test_ascending_ac_passthrough_and_derived_fields():
    llm = {
        "is_monster": True, "name": "Orc", "ac": 13, "ac_style": "ascending",
        "thac0": None, "hd_dice": "1d8+1",
        "attacks": [{"name": "claw", "bonus": 1, "damage_dice": "1d4"}],
        "move": "30'", "special_abilities": [], "environments": ["wilderness"],
        "confidence": 0.9,
    }
    entry = build_entry_from_llm(llm, make_candidate(), get_profile("dcc"))
    assert entry["ac"] == 13
    assert entry["hp_avg"] == 5.5
    assert entry["hd_value"] == 1.0
    attacks = json.loads(entry["attacks"])
    assert attacks[0]["bonus"] == 1
    assert attacks[0]["damage_avg"] == 2.5
    assert json.loads(entry["flags"]) == []
    assert entry["review_status"] == "pending"
    assert entry["page_number"] == 12
    assert entry["system_profile"] == "dcc"


def test_descending_ac_and_thac0_are_normalized():
    llm = {
        "is_monster": True, "name": "Peryton", "ac": 7, "ac_style": "descending",
        "thac0": 15, "hd_dice": "4d8",
        "attacks": [{"name": "antlers", "bonus": None, "damage_dice": "2d4"}],
        "move": "240'", "special_abilities": ["heart-eating"],
        "environments": ["mountains"], "confidence": 0.8,
    }
    entry = build_entry_from_llm(llm, make_candidate(name_guess="Peryton", page=142), get_profile("osr"))
    assert entry["ac"] == 12            # 19 - 7
    attacks = json.loads(entry["attacks"])
    assert attacks[0]["bonus"] == 5     # 20 - 15


def test_validation_flags():
    llm = {
        "is_monster": True, "name": "Weird Thing", "ac": 45, "ac_style": "ascending",
        "thac0": None, "hd_dice": "special", "attacks": [],
        "move": None, "special_abilities": [], "environments": [], "confidence": 0.4,
    }
    entry = build_entry_from_llm(llm, make_candidate(), get_profile("dcc"))
    flags = json.loads(entry["flags"])
    assert "ac_out_of_range" in flags
    assert "hd_unparseable" in flags
    assert "no_attacks" in flags
    assert entry["review_status"] == "pending"


async def test_normalize_candidate_calls_llm(monkeypatch):
    captured = {}

    async def fake_llm(text, prompt_template, api_key, model):
        captured["text"] = text
        return {
            "is_monster": True, "name": "Orc", "ac": 13, "ac_style": "ascending",
            "thac0": None, "hd_dice": "1d8+1",
            "attacks": [{"name": "claw", "bonus": 1, "damage_dice": "1d4"}],
            "move": "30'", "special_abilities": [], "environments": [],
            "confidence": 0.9,
        }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("grimoire.processors.monster_normalizer.extract_with_anthropic", fake_llm)

    entry = await normalize_candidate(make_candidate(), get_profile("dcc"))
    assert entry["name"] == "Orc"
    assert "AC 13" in captured["text"]


async def test_normalize_candidate_skips_non_monster(monkeypatch):
    async def fake_llm(text, prompt_template, api_key, model):
        return {"is_monster": False}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("grimoire.processors.monster_normalizer.extract_with_anthropic", fake_llm)

    assert await normalize_candidate(make_candidate(), get_profile("dcc")) is None
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/`: `python -m pytest tests/test_monster_normalizer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# backend/grimoire/processors/monster_normalizer.py
"""LLM normalization of monster candidates into MonsterEntry field dicts."""

import json
import logging
import os

from grimoire.processors.monster_segmenter import Candidate
from grimoire.processors.structured_extractor import (
    extract_with_anthropic,
    extract_with_openai,
)
from grimoire.processors.system_profiles import (
    SystemProfile,
    normalize_descending_ac,
    normalize_thac0,
)
from grimoire.utils.dice import dice_average, parse_dice

logger = logging.getLogger(__name__)

NORMALIZE_PROMPT = """You are normalizing a monster stat block candidate from a tabletop RPG book.

{profile_hint}

Report values EXACTLY as printed - do not convert or invent anything. If the
text is not actually a monster/creature stat block, return {{"is_monster": false}}.

Return ONLY this JSON shape:
{{"is_monster": true, "name": str, "ac": int or null,
 "ac_style": "ascending" or "descending", "thac0": int or null,
 "hd_dice": str or null, "attacks": [{{"name": str, "bonus": int or null, "damage_dice": str or null}}],
 "move": str or null, "special_abilities": [str], "environments": [str],
 "confidence": float 0-1}}

For "environments", infer terrain/habitat tags from the descriptive prose
(e.g. "forest", "mountains", "underground", "swamp", "desert", "aquatic",
"urban", "wilderness"). Use [] if nothing is stated or implied.

Candidate text:
{text}

Return ONLY valid JSON."""

_DEFAULT_MODELS = {"openai": "gpt-4o-mini", "anthropic": "claude-haiku-4-5"}


def build_entry_from_llm(llm: dict, candidate: Candidate, profile: SystemProfile) -> dict:
    """Pure normalization + validation of LLM output into MonsterEntry fields."""
    flags: list[str] = []

    ac = llm.get("ac")
    if ac is not None and llm.get("ac_style") == "descending":
        ac = normalize_descending_ac(int(ac))
    if ac is not None and not (0 <= int(ac) <= 30):
        flags.append("ac_out_of_range")

    thac0 = llm.get("thac0")
    attacks = []
    for atk in llm.get("attacks") or []:
        bonus = atk.get("bonus")
        if bonus is None and thac0 is not None:
            bonus = normalize_thac0(int(thac0))
        damage_dice = atk.get("damage_dice")
        damage_avg = dice_average(damage_dice)
        if damage_dice and damage_avg is None:
            flags.append("damage_unparseable")
        attacks.append({
            "name": atk.get("name") or "attack",
            "bonus": bonus,
            "damage_dice": damage_dice,
            "damage_avg": damage_avg,
        })
    if not attacks:
        flags.append("no_attacks")

    hd_dice = llm.get("hd_dice")
    hp_avg = dice_average(hd_dice)
    parsed_hd = parse_dice(hd_dice)
    hd_value = float(parsed_hd[0]) if parsed_hd else None
    if hd_dice and parsed_hd is None:
        flags.append("hd_unparseable")

    return {
        "name": llm.get("name") or candidate.name_guess,
        "page_number": candidate.page,
        "system_profile": profile.id,
        "raw_text": candidate.raw_text,
        "ac": int(ac) if ac is not None else None,
        "hd_dice": hd_dice,
        "hd_value": hd_value,
        "hp_avg": hp_avg,
        "attacks": json.dumps(attacks),
        "move": llm.get("move"),
        "special_abilities": json.dumps(llm.get("special_abilities") or []),
        "environments": json.dumps(llm.get("environments") or []),
        "extraction_confidence": llm.get("confidence"),
        "flags": json.dumps(sorted(set(flags))),
        "review_status": "pending",
    }


async def normalize_candidate(
    candidate: Candidate,
    profile: SystemProfile,
    provider: str | None = None,
    model: str | None = None,
) -> dict | None:
    """Send one candidate through the LLM and normalize the result.

    Returns None when no provider is configured or the LLM rejects the
    candidate as not-a-monster. Raises on transport errors (caller flags).
    """
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if provider is None:
        provider = "anthropic" if anthropic_key else "openai" if openai_key else None

    prompt_template = NORMALIZE_PROMPT.replace("{profile_hint}", profile.prompt_hint)

    if provider == "anthropic" and anthropic_key:
        llm = await extract_with_anthropic(
            candidate.raw_text, prompt_template, anthropic_key, model or _DEFAULT_MODELS["anthropic"]
        )
    elif provider == "openai" and openai_key:
        llm = await extract_with_openai(
            candidate.raw_text, prompt_template, openai_key, model or _DEFAULT_MODELS["openai"]
        )
    else:
        logger.warning("No AI provider configured for monster normalization")
        return None

    if not llm or not llm.get("is_monster"):
        return None
    return build_entry_from_llm(llm, candidate, profile)
```

Note: `NORMALIZE_PROMPT` keeps `{text}` as the only `.format` placeholder (the existing `extract_with_*` helpers call `prompt_template.format(text=...)`), which is why `profile_hint` is spliced with `.replace` and all literal JSON braces are doubled.

- [ ] **Step 4: Run tests to verify they pass**

From `backend/`: `python -m pytest tests/test_monster_normalizer.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/processors/monster_normalizer.py backend/tests/test_monster_normalizer.py
git commit -m "feat(bestiary): LLM candidate normalization with validation flags"
```

---

### Task 6: Metrics service

**Files:**
- Create: `backend/grimoire/services/monster_metrics.py`
- Test: `backend/tests/test_monster_metrics.py`

**Interfaces:**
- Consumes: `MonsterEntry` (Task 3), `get_profile` (Task 2)
- Produces: `compute_metrics(entry: MonsterEntry) -> dict`:

```python
{"hp_avg": 5.5,
 "tiers": [{"tier": "unarmored", "ac": 10,
            "attacks": [{"name": "claw", "hit_chance": 0.6, "dpr": 1.5}],
            "total_dpr": 1.5}, ...]}
```

Hit chance: `p = (21 + bonus - tier_ac) / 20`, clamped to `[0.05, 0.95]` (nat 1 always misses, nat 20 always hits). Attacks missing `bonus` contribute `hit_chance: None, dpr: None` and are excluded from `total_dpr`. Attacks with a bonus but missing `damage_avg` report their computed `hit_chance` with `dpr: None`, and are also excluded from `total_dpr`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_monster_metrics.py
"""Tests for closed-form combat metrics."""

import json

import pytest

from grimoire.models import MonsterEntry
from grimoire.services.monster_metrics import compute_metrics


def make_entry(**kwargs):
    defaults = dict(
        product_id=1, name="Orc", system_profile="dcc", raw_text="x",
        ac=13, hd_dice="1d8+1", hd_value=1.0, hp_avg=5.5,
        attacks=json.dumps([{"name": "claw", "bonus": 1, "damage_dice": "1d4", "damage_avg": 2.5}]),
        review_status="confirmed",
    )
    defaults.update(kwargs)
    return MonsterEntry(**defaults)


def test_hit_chance_and_dpr_vs_tiers():
    metrics = compute_metrics(make_entry())
    assert metrics["hp_avg"] == 5.5
    tiers = {t["tier"]: t for t in metrics["tiers"]}
    # DCC tiers: unarmored 10, leather 12, chain 15, plate & shield 19
    assert tiers["unarmored"]["attacks"][0]["hit_chance"] == pytest.approx(0.6)   # (21+1-10)/20
    assert tiers["unarmored"]["total_dpr"] == pytest.approx(1.5)                  # 0.6 * 2.5
    assert tiers["chain"]["attacks"][0]["hit_chance"] == pytest.approx(0.35)      # (21+1-15)/20
    assert tiers["plate & shield"]["attacks"][0]["hit_chance"] == pytest.approx(0.15)


def test_hit_chance_clamped():
    strong = make_entry(attacks=json.dumps([{"name": "bite", "bonus": 30, "damage_dice": "1d6", "damage_avg": 3.5}]))
    weak = make_entry(attacks=json.dumps([{"name": "peck", "bonus": -20, "damage_dice": "1", "damage_avg": 1.0}]))
    strong_tiers = compute_metrics(strong)["tiers"]
    weak_tiers = compute_metrics(weak)["tiers"]
    assert all(t["attacks"][0]["hit_chance"] == 0.95 for t in strong_tiers)
    assert all(t["attacks"][0]["hit_chance"] == 0.05 for t in weak_tiers)


def test_missing_bonus_yields_none_and_excluded_from_total():
    entry = make_entry(attacks=json.dumps([
        {"name": "claw", "bonus": 1, "damage_dice": "1d4", "damage_avg": 2.5},
        {"name": "gaze", "bonus": None, "damage_dice": None, "damage_avg": None},
    ]))
    tiers = compute_metrics(entry)["tiers"]
    unarmored = tiers[0]
    assert unarmored["attacks"][1]["hit_chance"] is None
    assert unarmored["total_dpr"] == pytest.approx(1.5)


def test_no_attacks():
    metrics = compute_metrics(make_entry(attacks=json.dumps([])))
    assert metrics["tiers"][0]["total_dpr"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/`: `python -m pytest tests/test_monster_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# backend/grimoire/services/monster_metrics.py
"""Closed-form combat metrics over normalized monster statlines.

Consumes probabilities, not mechanics: the normalized attack bonus encodes a
d20 hit-probability line. A future non-d20 profile would supply a different
curve here without touching callers.
"""

import json

from grimoire.models.monster_entry import MonsterEntry
from grimoire.processors.system_profiles import get_profile

_MIN_P = 0.05  # natural 1 always misses
_MAX_P = 0.95  # natural 20 always hits


def hit_chance(bonus: int, target_ac: int) -> float:
    """P(d20 + bonus >= target_ac), clamped for natural 1/20."""
    return max(_MIN_P, min(_MAX_P, (21 + bonus - target_ac) / 20))


def compute_metrics(entry: MonsterEntry) -> dict:
    """Hit chance and damage-per-round vs. the profile's armor tiers."""
    profile = get_profile(entry.system_profile)
    attacks = json.loads(entry.attacks) if entry.attacks else []

    tiers = []
    for tier_name, tier_ac in profile.armor_tiers.items():
        tier_attacks = []
        total_dpr = 0.0
        for atk in attacks:
            bonus, damage_avg = atk.get("bonus"), atk.get("damage_avg")
            if bonus is None:
                tier_attacks.append({"name": atk.get("name"), "hit_chance": None, "dpr": None})
                continue
            p = hit_chance(int(bonus), tier_ac)
            dpr = round(p * damage_avg, 2) if damage_avg is not None else None
            if dpr is not None:
                total_dpr += dpr
            tier_attacks.append({"name": atk.get("name"), "hit_chance": p, "dpr": dpr})
        tiers.append({
            "tier": tier_name,
            "ac": tier_ac,
            "attacks": tier_attacks,
            "total_dpr": round(total_dpr, 2),
        })

    return {"hp_avg": entry.hp_avg, "tiers": tiers}
```

- [ ] **Step 4: Run tests to verify they pass**

From `backend/`: `python -m pytest tests/test_monster_metrics.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/monster_metrics.py backend/tests/test_monster_metrics.py
git commit -m "feat(bestiary): closed-form hit chance and DPR metrics vs armor tiers"
```

---

### Task 7: Queue handler `monster_extract`

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py` (append a new `@register_handler` after the existing ones, e.g. after `handle_ai_identify_task`)
- Test: `backend/tests/test_monster_extract_handler.py`

**Interfaces:**
- Consumes: `get_extracted_pages(product)` (existing, `grimoire.services.processor`), `segment_pages`, `normalize_candidate`, `get_profile`, `MonsterEntry`. Dispatcher calls handlers as `await handler(db, product, config=item_config)` when the signature has `config` (it inspects the signature); returning `False` triggers the retry/attempts logic.
- Produces: handler `handle_monster_extract_task(db, product, config) -> bool` registered as task type `"monster_extract"`. Config keys: `system_profile` (required), `provider`, `model` (optional).

Re-run semantics: before inserting, delete this product's existing `pending`/`rejected` entries (stale machine output); keep `confirmed` rows and skip any candidate whose `(name, page)` matches a confirmed entry (don't clobber human review). Per-candidate LLM failures append the name to a log warning and continue — one mangled block never kills the run. Returns `False` (retryable) only when the product has no page-anchored text or the profile id is unknown.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_monster_extract_handler.py
"""Tests for the monster_extract queue handler (LLM mocked)."""

import json

from sqlalchemy import select

from grimoire.models import MonsterEntry, Product
from grimoire.services.queue_processor import handle_monster_extract_task

DCC_PAGES = [{"page": 12, "markdown": (
    "## Orc\n\nRaiders of the wastes.\n\n"
    "Orc: Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; MV 30'; Act 1d20; "
    "SV Fort +1, Ref +0, Will -1; AL C.\n"
)}]


def fake_entry(name="Orc", page=12):
    return {
        "name": name, "page_number": page, "system_profile": "dcc",
        "raw_text": "raw", "ac": 13, "hd_dice": "1d8+1", "hd_value": 1.0,
        "hp_avg": 5.5,
        "attacks": json.dumps([{"name": "claw", "bonus": 1, "damage_dice": "1d4", "damage_avg": 2.5}]),
        "move": "30'", "special_abilities": json.dumps([]),
        "environments": json.dumps(["wilderness"]), "extraction_confidence": 0.9,
        "flags": json.dumps([]), "review_status": "pending",
    }


async def make_product(db, path):
    product = Product(file_path=path, file_name=path.rsplit("/", 1)[-1], file_size=1, file_hash=path)
    db.add(product)
    await db.flush()
    return product


async def test_handler_persists_pending_entries(db, monkeypatch):
    product = await make_product(db, "/t/handler-basic.pdf")
    monkeypatch.setattr("grimoire.services.processor.get_extracted_pages", lambda p: DCC_PAGES)

    async def fake_normalize(candidate, profile, provider=None, model=None):
        return fake_entry()

    monkeypatch.setattr("grimoire.processors.monster_normalizer.normalize_candidate", fake_normalize)

    ok = await handle_monster_extract_task(db, product, config={"system_profile": "dcc"})
    assert ok is True
    result = await db.execute(select(MonsterEntry).where(MonsterEntry.product_id == product.id))
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].review_status == "pending"


async def test_handler_fails_without_pages(db, monkeypatch):
    product = await make_product(db, "/t/handler-nopages.pdf")
    monkeypatch.setattr("grimoire.services.processor.get_extracted_pages", lambda p: None)
    ok = await handle_monster_extract_task(db, product, config={"system_profile": "dcc"})
    assert ok is False


async def test_rerun_replaces_pending_but_keeps_confirmed(db, monkeypatch):
    product = await make_product(db, "/t/handler-rerun.pdf")
    confirmed = MonsterEntry(product_id=product.id, review_status="confirmed",
                             **{k: v for k, v in fake_entry().items() if k != "review_status"})
    stale = MonsterEntry(product_id=product.id, review_status="pending",
                         **{k: v for k, v in fake_entry(name="Stale Ghost", page=99).items() if k != "review_status"})
    db.add_all([confirmed, stale])
    await db.flush()

    monkeypatch.setattr("grimoire.services.processor.get_extracted_pages", lambda p: DCC_PAGES)

    async def fake_normalize(candidate, profile, provider=None, model=None):
        return fake_entry()  # same (name, page) as the confirmed row

    monkeypatch.setattr("grimoire.processors.monster_normalizer.normalize_candidate", fake_normalize)

    ok = await handle_monster_extract_task(db, product, config={"system_profile": "dcc"})
    assert ok is True
    result = await db.execute(select(MonsterEntry).where(MonsterEntry.product_id == product.id))
    entries = result.scalars().all()
    # Stale pending row deleted; confirmed kept; duplicate candidate skipped.
    assert len(entries) == 1
    assert entries[0].review_status == "confirmed"
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/`: `python -m pytest tests/test_monster_extract_handler.py -v`
Expected: FAIL with `ImportError: cannot import name 'handle_monster_extract_task'`

- [ ] **Step 3: Write the handler**

Append to `backend/grimoire/services/queue_processor.py` after the last existing handler:

```python
@register_handler("monster_extract")
async def handle_monster_extract_task(
    db: AsyncSession, product: Product, config: dict | None = None
) -> bool:
    """Extract monster entries from a bestiary product (segment -> LLM -> pending rows)."""
    import json as _json

    from sqlalchemy import delete, select as _select

    from grimoire.models.monster_entry import MonsterEntry
    from grimoire.processors import monster_normalizer
    from grimoire.processors.monster_segmenter import segment_pages
    from grimoire.processors.system_profiles import PROFILES
    from grimoire.services import processor as _processor

    config = config or {}
    profile_id = config.get("system_profile")
    if profile_id not in PROFILES:
        logger.error(f"monster_extract: unknown system profile '{profile_id}'")
        return False
    profile = PROFILES[profile_id]

    pages = _processor.get_extracted_pages(product)
    if not pages:
        logger.warning(
            f"monster_extract: no page-anchored text for '{product.file_name}' "
            "(re-run text extraction first)"
        )
        return False

    candidates = segment_pages(pages, profile)
    logger.info(f"monster_extract: {len(candidates)} candidates in '{product.file_name}'")

    # Replace stale machine output; never touch human-reviewed rows.
    await db.execute(
        delete(MonsterEntry).where(
            MonsterEntry.product_id == product.id,
            MonsterEntry.review_status.in_(["pending", "rejected"]),
        )
    )
    result = await db.execute(
        _select(MonsterEntry.name, MonsterEntry.page_number).where(
            MonsterEntry.product_id == product.id,
            MonsterEntry.review_status == "confirmed",
        )
    )
    confirmed_keys = {(row.name, row.page_number) for row in result}

    saved = failed = 0
    for candidate in candidates:
        try:
            entry = await monster_normalizer.normalize_candidate(
                candidate, profile,
                provider=config.get("provider"), model=config.get("model"),
            )
        except Exception as exc:
            failed += 1
            logger.warning(f"monster_extract: candidate '{candidate.name_guess}' failed: {exc}")
            continue
        if entry is None:
            continue
        if (entry["name"], entry["page_number"]) in confirmed_keys:
            continue
        db.add(MonsterEntry(product_id=product.id, **entry))
        saved += 1

    await db.commit()
    logger.info(
        f"monster_extract: saved {saved} pending entries for '{product.file_name}' "
        f"({failed} candidates failed)"
    )
    return True
```

Note: the test monkeypatches `grimoire.services.processor.get_extracted_pages` and `grimoire.processors.monster_normalizer.normalize_candidate` — the handler must call both through their modules (as written above), not via `from x import name` at call scope.

- [ ] **Step 4: Run tests to verify they pass**

From `backend/`: `python -m pytest tests/test_monster_extract_handler.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/grimoire/services/queue_processor.py backend/tests/test_monster_extract_handler.py
git commit -m "feat(bestiary): monster_extract queue handler"
```

---

### Task 8: Bestiary API routes

**Files:**
- Create: `backend/grimoire/api/routes/monsters.py`
- Modify: `backend/grimoire/api/routes/__init__.py` (import `monsters`, add `api_router.include_router(monsters.router, prefix="/monsters", tags=["Bestiary"])`)
- Test: `backend/tests/test_monsters_api.py`

**Interfaces:**
- Consumes: `MonsterEntry`, `ProcessingQueue`, `Product`, `compute_metrics`, `PROFILES`, `dice_average`/`parse_dice`, `DbSession` dependency from `grimoire.api.deps`
- Produces endpoints (all under `/api/v1/monsters`):
  - `POST /extract/{product_id}` — body `{"system_profile": "dcc", "provider": null, "model": null}`; 404 unknown product, 400 unknown profile or product without extracted text; enqueues `ProcessingQueue(task_type="monster_extract", priority=5, status="pending", config=json)`; skips if a pending/processing `monster_extract` item already exists for the product (returns `{"queued": false, "message": ...}`)
  - `GET /` — query params `environment, system_profile, product_id, review_status (default "confirmed"), q, hd_min, hd_max, page (default 1), per_page (default 50, max 200)`; returns `{"items": [entry dicts with parsed JSON fields + product_title], "total": int}`; environment filter uses `LIKE '%"<env>"%'` on the JSON text (pragmatic SQLite)
  - `GET /environments` — distinct environment tags across confirmed entries (for the filter dropdown)
  - `PATCH /{entry_id}` — partial update of `name, page_number, ac, hd_dice, attacks, move, special_abilities, environments, review_status`; if `hd_dice` changes, recompute `hd_value`/`hp_avg`; if `attacks` changes, recompute each `damage_avg`; validates `review_status` against the three allowed values (422 otherwise); returns the updated entry dict
  - `GET /{entry_id}/metrics` — `compute_metrics` result; 404 if missing
  - `POST /random` — body `{"count": 3, "environment": null, "system_profile": null, "hd_min": null, "hd_max": null, "product_id": null}`; random sample of **confirmed** entries matching filters (`ORDER BY RANDOM() LIMIT count` is fine at this scale); returns `{"items": [...]}` where each item includes `product_title` for the `Name — Book, p. X` rendering

Route functions must be directly awaitable in tests with a `db` session and explicit keyword args (the established pattern here — no HTTP test client).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_monsters_api.py
"""Tests for bestiary API routes (called directly with the db fixture)."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from grimoire.api.routes.monsters import (
    ExtractRequest,
    PatchEntryRequest,
    RandomRequest,
    enqueue_extract,
    get_entry_metrics,
    list_environments,
    list_monsters,
    patch_entry,
    random_monsters,
)
from grimoire.models import MonsterEntry, ProcessingQueue, Product


async def seed(db, path, name, env, status="confirmed", hd_value=1.0):
    product = Product(file_path=path, file_name=path.rsplit("/", 1)[-1],
                      file_size=1, file_hash=path, title="Test Bestiary",
                      text_extracted=True, extracted_text_path="/t/x.json")
    db.add(product)
    await db.flush()
    entry = MonsterEntry(
        product_id=product.id, name=name, page_number=10, system_profile="dcc",
        raw_text="raw", ac=13, hd_dice="1d8", hd_value=hd_value, hp_avg=4.5,
        attacks=json.dumps([{"name": "claw", "bonus": 1, "damage_dice": "1d4", "damage_avg": 2.5}]),
        environments=json.dumps([env]), special_abilities=json.dumps([]),
        flags=json.dumps([]), review_status=status,
    )
    db.add(entry)
    await db.flush()
    return product, entry


async def test_list_filters_by_environment_and_default_confirmed(db):
    await seed(db, "/t/api-list-1.pdf", "Forest Wolf", "forest")
    await seed(db, "/t/api-list-2.pdf", "Cave Ooze", "underground")
    await seed(db, "/t/api-list-3.pdf", "Pending Rat", "forest", status="pending")

    result = await list_monsters(db=db, environment="forest")
    names = [item["name"] for item in result["items"]]
    assert "Forest Wolf" in names
    assert "Cave Ooze" not in names
    assert "Pending Rat" not in names  # default review_status=confirmed

    pending = await list_monsters(db=db, environment="forest", review_status="pending")
    assert [i["name"] for i in pending["items"]] == ["Pending Rat"]


async def test_hd_range_filter(db):
    await seed(db, "/t/api-hd-1.pdf", "Big Troll", "hills", hd_value=6.0)
    result = await list_monsters(db=db, hd_min=5.0)
    names = [i["name"] for i in result["items"]]
    assert "Big Troll" in names
    assert all(i["hd_value"] >= 5.0 for i in result["items"])


async def test_patch_recomputes_derived_fields(db):
    _, entry = await seed(db, "/t/api-patch.pdf", "Patch Me", "swamp")
    updated = await patch_entry(
        db=db, entry_id=entry.id,
        request=PatchEntryRequest(hd_dice="3d8+3", review_status="confirmed"),
    )
    assert updated["hp_avg"] == 16.5
    assert updated["hd_value"] == 3.0
    assert updated["review_status"] == "confirmed"


async def test_patch_rejects_bad_status(db):
    _, entry = await seed(db, "/t/api-badstatus.pdf", "Bad Status", "swamp")
    with pytest.raises(HTTPException) as exc:
        await patch_entry(db=db, entry_id=entry.id, request=PatchEntryRequest(review_status="maybe"))
    assert exc.value.status_code == 422


async def test_metrics_endpoint(db):
    _, entry = await seed(db, "/t/api-metrics.pdf", "Metric Orc", "plains")
    metrics = await get_entry_metrics(db=db, entry_id=entry.id)
    assert metrics["hp_avg"] == 4.5
    assert metrics["tiers"][0]["tier"] == "unarmored"


async def test_random_returns_only_confirmed_with_product_title(db):
    await seed(db, "/t/api-rand-1.pdf", "Rand Wolf", "tundra")
    await seed(db, "/t/api-rand-2.pdf", "Rand Ghost", "tundra", status="pending")
    result = await random_monsters(db=db, request=RandomRequest(count=10, environment="tundra"))
    names = [i["name"] for i in result["items"]]
    assert "Rand Wolf" in names
    assert "Rand Ghost" not in names
    assert all(i["product_title"] for i in result["items"])


async def test_enqueue_extract(db):
    product, _ = await seed(db, "/t/api-enq.pdf", "Enq Orc", "forest")
    response = await enqueue_extract(
        db=db, product_id=product.id, request=ExtractRequest(system_profile="dcc")
    )
    assert response["queued"] is True
    result = await db.execute(select(ProcessingQueue).where(
        ProcessingQueue.product_id == product.id,
        ProcessingQueue.task_type == "monster_extract",
    ))
    item = result.scalars().first()
    assert item is not None
    assert json.loads(item.config)["system_profile"] == "dcc"

    again = await enqueue_extract(
        db=db, product_id=product.id, request=ExtractRequest(system_profile="dcc")
    )
    assert again["queued"] is False


async def test_enqueue_rejects_unknown_profile(db):
    product, _ = await seed(db, "/t/api-enq-bad.pdf", "Bad Prof", "forest")
    with pytest.raises(HTTPException) as exc:
        await enqueue_extract(db=db, product_id=product.id, request=ExtractRequest(system_profile="gurps"))
    assert exc.value.status_code == 400


async def test_environments_listing(db):
    await seed(db, "/t/api-envs.pdf", "Env Crab", "coastal")
    envs = await list_environments(db=db)
    assert "coastal" in envs["environments"]
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/`: `python -m pytest tests/test_monsters_api.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the routes**

```python
# backend/grimoire/api/routes/monsters.py
"""Bestiary API - extracted monster entries, encounter rolls, metrics."""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from grimoire.api.deps import DbSession
from grimoire.models import MonsterEntry, ProcessingQueue, Product
from grimoire.processors.system_profiles import PROFILES
from grimoire.services.monster_metrics import compute_metrics
from grimoire.utils.dice import dice_average, parse_dice

router = APIRouter()

VALID_STATUSES = {"pending", "confirmed", "rejected"}


class ExtractRequest(BaseModel):
    system_profile: str
    provider: str | None = None
    model: str | None = None


class PatchEntryRequest(BaseModel):
    name: str | None = None
    page_number: int | None = None
    ac: int | None = None
    hd_dice: str | None = None
    attacks: list[dict] | None = None
    move: str | None = None
    special_abilities: list[str] | None = None
    environments: list[str] | None = None
    review_status: str | None = None


class RandomRequest(BaseModel):
    count: int = Field(3, ge=1, le=50)
    environment: str | None = None
    system_profile: str | None = None
    hd_min: float | None = None
    hd_max: float | None = None
    product_id: int | None = None


def _entry_to_dict(entry: MonsterEntry, product_title: str | None = None) -> dict:
    return {
        "id": entry.id,
        "product_id": entry.product_id,
        "product_title": product_title,
        "name": entry.name,
        "page_number": entry.page_number,
        "system_profile": entry.system_profile,
        "raw_text": entry.raw_text,
        "ac": entry.ac,
        "hd_dice": entry.hd_dice,
        "hd_value": entry.hd_value,
        "hp_avg": entry.hp_avg,
        "attacks": json.loads(entry.attacks) if entry.attacks else [],
        "move": entry.move,
        "special_abilities": json.loads(entry.special_abilities) if entry.special_abilities else [],
        "environments": json.loads(entry.environments) if entry.environments else [],
        "extraction_confidence": entry.extraction_confidence,
        "flags": json.loads(entry.flags) if entry.flags else [],
        "review_status": entry.review_status,
    }


def _base_conditions(
    environment: str | None = None,
    system_profile: str | None = None,
    product_id: int | None = None,
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
    if product_id:
        conditions.append(MonsterEntry.product_id == product_id)
    if hd_min is not None:
        conditions.append(MonsterEntry.hd_value >= hd_min)
    if hd_max is not None:
        conditions.append(MonsterEntry.hd_value <= hd_max)
    if q:
        conditions.append(MonsterEntry.name.ilike(f"%{q}%"))
    return conditions


@router.post("/extract/{product_id}")
async def enqueue_extract(db: DbSession, product_id: int, request: ExtractRequest) -> dict:
    """Queue monster extraction for a bestiary product."""
    if request.system_profile not in PROFILES:
        raise HTTPException(status_code=400, detail=f"Unknown system profile: {request.system_profile}")

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not product.text_extracted:
        raise HTTPException(status_code=400, detail="Product has no extracted text")

    existing = await db.execute(select(ProcessingQueue).where(
        ProcessingQueue.product_id == product_id,
        ProcessingQueue.task_type == "monster_extract",
        ProcessingQueue.status.in_(["pending", "processing"]),
    ))
    if existing.scalars().first():
        return {"queued": False, "message": "Extraction already queued for this product"}

    config = {"system_profile": request.system_profile}
    if request.provider:
        config["provider"] = request.provider
    if request.model:
        config["model"] = request.model
    db.add(ProcessingQueue(
        product_id=product_id,
        task_type="monster_extract",
        priority=5,
        status="pending",
        config=json.dumps(config),
    ))
    await db.commit()
    return {"queued": True, "message": f"Monster extraction queued ({request.system_profile})"}


@router.get("/")
async def list_monsters(
    db: DbSession,
    environment: str | None = None,
    system_profile: str | None = None,
    product_id: int | None = None,
    review_status: str = "confirmed",
    q: str | None = None,
    hd_min: float | None = None,
    hd_max: float | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """List monster entries with filters. Defaults to confirmed entries only."""
    per_page = min(per_page, 200)
    conditions = _base_conditions(environment, system_profile, product_id, review_status, hd_min, hd_max, q)

    count_query = select(func.count(MonsterEntry.id)).where(*conditions)
    total = (await db.execute(count_query)).scalar() or 0

    query = (
        select(MonsterEntry, Product.title)
        .join(Product, Product.id == MonsterEntry.product_id)
        .where(*conditions)
        .order_by(MonsterEntry.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = (await db.execute(query)).all()
    return {"items": [_entry_to_dict(e, title) for e, title in rows], "total": total}


@router.get("/environments")
async def list_environments(db: DbSession) -> dict:
    """Distinct environment tags across confirmed entries."""
    result = await db.execute(
        select(MonsterEntry.environments).where(MonsterEntry.review_status == "confirmed")
    )
    tags: set[str] = set()
    for (raw,) in result:
        if raw:
            tags.update(json.loads(raw))
    return {"environments": sorted(tags)}


@router.patch("/{entry_id}")
async def patch_entry(db: DbSession, entry_id: int, request: PatchEntryRequest) -> dict:
    """Edit an entry; recompute derived fields when dice change."""
    result = await db.execute(select(MonsterEntry).where(MonsterEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    if request.review_status is not None:
        if request.review_status not in VALID_STATUSES:
            raise HTTPException(status_code=422, detail=f"review_status must be one of {sorted(VALID_STATUSES)}")
        entry.review_status = request.review_status

    for field in ("name", "page_number", "ac", "move"):
        value = getattr(request, field)
        if value is not None:
            setattr(entry, field, value)

    if request.hd_dice is not None:
        entry.hd_dice = request.hd_dice
        entry.hp_avg = dice_average(request.hd_dice)
        parsed = parse_dice(request.hd_dice)
        entry.hd_value = float(parsed[0]) if parsed else None

    if request.attacks is not None:
        attacks = []
        for atk in request.attacks:
            atk = dict(atk)
            atk["damage_avg"] = dice_average(atk.get("damage_dice"))
            attacks.append(atk)
        entry.attacks = json.dumps(attacks)

    if request.special_abilities is not None:
        entry.special_abilities = json.dumps(request.special_abilities)
    if request.environments is not None:
        entry.environments = json.dumps(request.environments)

    await db.commit()
    await db.refresh(entry)
    return _entry_to_dict(entry)


@router.get("/{entry_id}/metrics")
async def get_entry_metrics(db: DbSession, entry_id: int) -> dict:
    """Closed-form combat metrics for one entry."""
    result = await db.execute(select(MonsterEntry).where(MonsterEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return compute_metrics(entry)


@router.post("/random")
async def random_monsters(db: DbSession, request: RandomRequest) -> dict:
    """Random confirmed monsters matching filters (encounter roll / table rows)."""
    conditions = _base_conditions(
        environment=request.environment,
        system_profile=request.system_profile,
        product_id=request.product_id,
        review_status="confirmed",
        hd_min=request.hd_min,
        hd_max=request.hd_max,
    )
    query = (
        select(MonsterEntry, Product.title)
        .join(Product, Product.id == MonsterEntry.product_id)
        .where(*conditions)
        .order_by(func.random())
        .limit(request.count)
    )
    rows = (await db.execute(query)).all()
    return {"items": [_entry_to_dict(e, title) for e, title in rows]}
```

Route order note: `/environments` and `/random` are declared before `/{entry_id}`-shaped routes conflict — FastAPI matches literal paths first only if declared first; keep `GET /environments` above `GET /{entry_id}/metrics` as written.

In `backend/grimoire/api/routes/__init__.py`: add `monsters` to the existing import line and register:

```python
api_router.include_router(monsters.router, prefix="/monsters", tags=["Bestiary"])
```

- [ ] **Step 4: Run tests to verify they pass**

From `backend/`: `python -m pytest tests/test_monsters_api.py -v`
Expected: 9 PASS

- [ ] **Step 5: Run the whole backend suite for regressions**

From `backend/`: `python -m pytest`
Expected: all new tests pass; only the 7 pre-existing baseline failures remain.

- [ ] **Step 6: Commit**

```bash
git add backend/grimoire/api/routes/monsters.py backend/grimoire/api/routes/__init__.py backend/tests/test_monsters_api.py
git commit -m "feat(bestiary): monsters API - extract, browse, review, metrics, random"
```

---

### Task 9: Frontend — API client and Bestiary page

**Files:**
- Create: `frontend/src/api/monsters.ts`
- Create: `frontend/src/pages/Bestiary.tsx`
- Modify: `frontend/src/components/NavRail.tsx` (add nav item)
- Modify: `frontend/src/App.tsx` (import + render branch)

**Interfaces:**
- Consumes: backend endpoints from Task 8; `api` axios instance from `frontend/src/api/client.ts` (baseURL `/api/v1`); React Query v5 (`useQuery`, `useMutation`, `useQueryClient`); CSS variable theming (`var(--color-*)`) per NavRail convention — no new Tailwind color utilities
- Consumes (also): `getProducts(filters)` from `frontend/src/api/products.ts` (existing: `ProductFilters` has `search`, `per_page`; returns `{ items: Product[], total: number }` where `Product` has `id`, `title`, `file_name`)
- Produces: `Bestiary` page component (named export, matching `pages/` convention) with: an "Extract from book" panel (product search via `getProducts` + profile picker + queue button — this is the spec's per-product designate action), filter bar (environment dropdown from `/monsters/environments`, HD min/max, system profile, review-status toggle, name search), entry list with expandable metrics panel (`GET /monsters/{id}/metrics`), "Roll" buttons (`POST /monsters/random`), rollable table generator (client-side numbering, rows `Name — Book, p. X`), and review controls (confirm/reject + inline edits via `PATCH /monsters/{id}`) shown when the review-status filter is `pending`

- [ ] **Step 1: Write the API client**

```typescript
// frontend/src/api/monsters.ts
import api from './client';

export interface MonsterAttack {
  name: string;
  bonus: number | null;
  damage_dice: string | null;
  damage_avg: number | null;
}

export interface MonsterEntry {
  id: number;
  product_id: number;
  product_title: string | null;
  name: string;
  page_number: number | null;
  system_profile: string;
  raw_text: string;
  ac: number | null;
  hd_dice: string | null;
  hd_value: number | null;
  hp_avg: number | null;
  attacks: MonsterAttack[];
  move: string | null;
  special_abilities: string[];
  environments: string[];
  extraction_confidence: number | null;
  flags: string[];
  review_status: 'pending' | 'confirmed' | 'rejected';
}

export interface MonsterFilters {
  environment?: string;
  system_profile?: string;
  product_id?: number;
  review_status?: string;
  q?: string;
  hd_min?: number;
  hd_max?: number;
  page?: number;
  per_page?: number;
}

export interface TierMetrics {
  tier: string;
  ac: number;
  attacks: { name: string; hit_chance: number | null; dpr: number | null }[];
  total_dpr: number;
}

export interface MonsterMetrics {
  hp_avg: number | null;
  tiers: TierMetrics[];
}

export async function listMonsters(filters: MonsterFilters) {
  const { data } = await api.get<{ items: MonsterEntry[]; total: number }>('/monsters/', {
    params: filters,
  });
  return data;
}

export async function listEnvironments() {
  const { data } = await api.get<{ environments: string[] }>('/monsters/environments');
  return data.environments;
}

export async function getMetrics(entryId: number) {
  const { data } = await api.get<MonsterMetrics>(`/monsters/${entryId}/metrics`);
  return data;
}

export async function patchMonster(entryId: number, patch: Partial<MonsterEntry>) {
  const { data } = await api.patch<MonsterEntry>(`/monsters/${entryId}`, patch);
  return data;
}

export async function rollRandom(params: {
  count: number;
  environment?: string;
  system_profile?: string;
  hd_min?: number;
  hd_max?: number;
  product_id?: number;
}) {
  const { data } = await api.post<{ items: MonsterEntry[] }>('/monsters/random', params);
  return data.items;
}

export async function queueExtraction(productId: number, systemProfile: string) {
  const { data } = await api.post<{ queued: boolean; message: string }>(
    `/monsters/extract/${productId}`,
    { system_profile: systemProfile },
  );
  return data;
}
```

- [ ] **Step 2: Write the Bestiary page**

Create `frontend/src/pages/Bestiary.tsx` with the complete component below. Styling: match the surrounding app — CSS variables (`var(--color-bg)`, `var(--color-text)`, `var(--color-border)`, etc. — copy the exact variable names used in `pages/Gallery.tsx`) with Tailwind spacing/layout utilities only; adjust variable names if Gallery uses different ones, but keep the structure and logic exactly as written:

```tsx
// frontend/src/pages/Bestiary.tsx
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listMonsters, listEnvironments, getMetrics, patchMonster, rollRandom, queueExtraction,
  type MonsterEntry, type MonsterFilters,
} from '../api/monsters';
import { getProducts } from '../api/products';

const TABLE_SIZES = [4, 6, 8, 10, 12, 20];

function cite(entry: MonsterEntry): string {
  return `${entry.name} — ${entry.product_title ?? 'Unknown book'}, p. ${entry.page_number ?? '?'}`;
}

export function Bestiary() {
  const [filters, setFilters] = useState<MonsterFilters>({ review_status: 'confirmed' });
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [rolled, setRolled] = useState<MonsterEntry[]>([]);
  const [tableSize, setTableSize] = useState(8);
  const [showExtract, setShowExtract] = useState(false);
  const [productSearch, setProductSearch] = useState('');
  const [extractProfile, setExtractProfile] = useState<'dcc' | 'osr'>('dcc');
  const [extractMessage, setExtractMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: environments = [] } = useQuery({
    queryKey: ['monster-environments'],
    queryFn: listEnvironments,
  });
  const { data, isLoading } = useQuery({
    queryKey: ['monsters', filters],
    queryFn: () => listMonsters(filters),
  });
  const { data: metrics } = useQuery({
    queryKey: ['monster-metrics', expandedId],
    queryFn: () => getMetrics(expandedId!),
    enabled: expandedId !== null,
  });
  const { data: productResults } = useQuery({
    queryKey: ['bestiary-product-search', productSearch],
    queryFn: () => getProducts({ search: productSearch, per_page: 10 }),
    enabled: showExtract && productSearch.length >= 2,
  });

  const patchMutation = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<MonsterEntry> }) =>
      patchMonster(id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monsters'] }),
  });
  const extractMutation = useMutation({
    mutationFn: ({ productId, profile }: { productId: number; profile: string }) =>
      queueExtraction(productId, profile),
    onSuccess: (result) => setExtractMessage(result.message),
    onError: (err: any) =>
      setExtractMessage(err?.response?.data?.detail ?? 'Failed to queue extraction'),
  });

  const setFilter = (patch: Partial<MonsterFilters>) =>
    setFilters((prev) => ({ ...prev, ...patch }));

  const roll = async (count: number) => {
    setRolled(await rollRandom({
      count,
      environment: filters.environment,
      system_profile: filters.system_profile,
      hd_min: filters.hd_min,
      hd_max: filters.hd_max,
    }));
  };

  const reviewMode = filters.review_status === 'pending';
  const items = data?.items ?? [];

  return (
    <div className="h-full overflow-y-auto p-4" style={{ color: 'var(--color-text)' }}>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">Bestiary</h1>
        <button className="px-3 py-1.5 rounded border" style={{ borderColor: 'var(--color-border)' }}
          onClick={() => { setShowExtract(!showExtract); setExtractMessage(null); }}>
          Extract from book…
        </button>
      </div>

      {showExtract && (
        <div className="mb-4 p-3 rounded border" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex gap-2 items-center flex-wrap">
            <input className="px-2 py-1 rounded border flex-1 min-w-[200px] bg-transparent"
              style={{ borderColor: 'var(--color-border)' }}
              placeholder="Search your library… (min 2 chars)"
              value={productSearch} onChange={(e) => setProductSearch(e.target.value)} />
            <select value={extractProfile} className="px-2 py-1 rounded border bg-transparent"
              style={{ borderColor: 'var(--color-border)' }}
              onChange={(e) => setExtractProfile(e.target.value as 'dcc' | 'osr')}>
              <option value="dcc">DCC</option>
              <option value="osr">Generic OSR</option>
            </select>
          </div>
          {(productResults?.items ?? []).map((p) => (
            <div key={p.id} className="flex items-center justify-between py-1 text-sm">
              <span>{p.title ?? p.file_name}</span>
              <button className="px-2 py-0.5 rounded border" style={{ borderColor: 'var(--color-border)' }}
                disabled={extractMutation.isPending}
                onClick={() => extractMutation.mutate({ productId: p.id, profile: extractProfile })}>
                Extract monsters
              </button>
            </div>
          ))}
          {extractMessage && <p className="text-sm mt-2 opacity-80">{extractMessage}</p>}
        </div>
      )}

      <div className="flex gap-2 items-end flex-wrap mb-4">
        <select className="px-2 py-1 rounded border bg-transparent" style={{ borderColor: 'var(--color-border)' }}
          value={filters.environment ?? ''}
          onChange={(e) => setFilter({ environment: e.target.value || undefined })}>
          <option value="">All environments</option>
          {environments.map((env) => <option key={env} value={env}>{env}</option>)}
        </select>
        <select className="px-2 py-1 rounded border bg-transparent" style={{ borderColor: 'var(--color-border)' }}
          value={filters.system_profile ?? ''}
          onChange={(e) => setFilter({ system_profile: e.target.value || undefined })}>
          <option value="">All systems</option>
          <option value="dcc">DCC</option>
          <option value="osr">OSR</option>
        </select>
        <input type="number" className="w-20 px-2 py-1 rounded border bg-transparent"
          style={{ borderColor: 'var(--color-border)' }} placeholder="HD min"
          value={filters.hd_min ?? ''}
          onChange={(e) => setFilter({ hd_min: e.target.value ? Number(e.target.value) : undefined })} />
        <input type="number" className="w-20 px-2 py-1 rounded border bg-transparent"
          style={{ borderColor: 'var(--color-border)' }} placeholder="HD max"
          value={filters.hd_max ?? ''}
          onChange={(e) => setFilter({ hd_max: e.target.value ? Number(e.target.value) : undefined })} />
        <input className="px-2 py-1 rounded border bg-transparent flex-1 min-w-[160px]"
          style={{ borderColor: 'var(--color-border)' }} placeholder="Search name…"
          value={filters.q ?? ''}
          onChange={(e) => setFilter({ q: e.target.value || undefined })} />
        <button className="px-3 py-1 rounded border" style={{ borderColor: 'var(--color-border)' }}
          onClick={() => setFilter({ review_status: reviewMode ? 'confirmed' : 'pending' })}>
          {reviewMode ? 'Show confirmed' : 'Review pending'}
        </button>
      </div>

      {!reviewMode && (
        <div className="flex gap-2 items-center mb-4">
          <button className="px-3 py-1 rounded border" style={{ borderColor: 'var(--color-border)' }}
            onClick={() => roll(3)}>Roll 3 random</button>
          <select className="px-2 py-1 rounded border bg-transparent" style={{ borderColor: 'var(--color-border)' }}
            value={tableSize} onChange={(e) => setTableSize(Number(e.target.value))}>
            {TABLE_SIZES.map((n) => <option key={n} value={n}>d{n}</option>)}
          </select>
          <button className="px-3 py-1 rounded border" style={{ borderColor: 'var(--color-border)' }}
            onClick={() => roll(tableSize)}>Generate d{tableSize} table</button>
          {rolled.length > 0 && (
            <button className="px-2 py-1 text-sm opacity-70" onClick={() => setRolled([])}>Clear</button>
          )}
        </div>
      )}

      {rolled.length > 0 && !reviewMode && (
        <table className="mb-4 text-sm w-full max-w-2xl">
          <tbody>
            {rolled.map((entry, i) => (
              <tr key={`${entry.id}-${i}`} className="border-b" style={{ borderColor: 'var(--color-border)' }}>
                <td className="py-1 pr-3 w-8 font-mono">{i + 1}</td>
                <td className="py-1">{cite(entry)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {isLoading && <p className="opacity-70">Loading…</p>}
      {!isLoading && items.length === 0 && (
        <p className="opacity-70">
          {reviewMode
            ? 'No pending entries. Queue an extraction with "Extract from book…" above.'
            : 'No confirmed monsters yet. Extract a bestiary, then confirm entries in Review pending.'}
        </p>
      )}

      <div className="space-y-2">
        {items.map((entry) => (
          <div key={entry.id} className="rounded border p-3" style={{ borderColor: 'var(--color-border)' }}>
            <div className="flex items-center justify-between cursor-pointer"
              onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}>
              <div>
                <span className="font-medium">{entry.name}</span>
                <span className="opacity-70 text-sm ml-2">
                  {entry.product_title ?? 'Unknown book'}, p. {entry.page_number ?? '?'}
                </span>
              </div>
              <div className="text-sm opacity-80 flex gap-3">
                <span>AC {entry.ac ?? '?'}</span>
                <span>HD {entry.hd_dice ?? '?'}</span>
                {entry.environments.map((env) => (
                  <span key={env} className="px-1.5 rounded text-xs border"
                    style={{ borderColor: 'var(--color-border)' }}>{env}</span>
                ))}
              </div>
            </div>

            {reviewMode && (
              <div className="mt-2 space-y-2">
                {entry.flags.length > 0 && (
                  <div className="flex gap-1">
                    {entry.flags.map((flag) => (
                      <span key={flag} className="text-xs px-1.5 rounded"
                        style={{ backgroundColor: 'var(--color-warning, #a16207)', color: '#fff' }}>
                        {flag}
                      </span>
                    ))}
                  </div>
                )}
                <pre className="text-xs p-2 rounded overflow-x-auto border whitespace-pre-wrap"
                  style={{ borderColor: 'var(--color-border)' }}>{entry.raw_text}</pre>
                <div className="flex gap-2 items-center text-sm">
                  <label>Name <input className="px-1 border rounded bg-transparent"
                    style={{ borderColor: 'var(--color-border)' }} defaultValue={entry.name}
                    onBlur={(e) => e.target.value !== entry.name &&
                      patchMutation.mutate({ id: entry.id, patch: { name: e.target.value } })} /></label>
                  <label>AC <input type="number" className="w-16 px-1 border rounded bg-transparent"
                    style={{ borderColor: 'var(--color-border)' }} defaultValue={entry.ac ?? ''}
                    onBlur={(e) => e.target.value !== String(entry.ac ?? '') &&
                      patchMutation.mutate({ id: entry.id, patch: { ac: Number(e.target.value) } })} /></label>
                  <label>HD <input className="w-20 px-1 border rounded bg-transparent"
                    style={{ borderColor: 'var(--color-border)' }} defaultValue={entry.hd_dice ?? ''}
                    onBlur={(e) => e.target.value !== (entry.hd_dice ?? '') &&
                      patchMutation.mutate({ id: entry.id, patch: { hd_dice: e.target.value } })} /></label>
                  <button className="px-2 py-0.5 rounded border ml-auto"
                    style={{ borderColor: 'var(--color-border)' }}
                    onClick={() => patchMutation.mutate({ id: entry.id, patch: { review_status: 'confirmed' } })}>
                    Confirm
                  </button>
                  <button className="px-2 py-0.5 rounded border opacity-70"
                    style={{ borderColor: 'var(--color-border)' }}
                    onClick={() => patchMutation.mutate({ id: entry.id, patch: { review_status: 'rejected' } })}>
                    Reject
                  </button>
                </div>
              </div>
            )}

            {expandedId === entry.id && metrics && (
              <div className="mt-3 text-sm">
                <p className="mb-1">Average HP: {metrics.hp_avg ?? '?'}</p>
                <table className="w-full max-w-md">
                  <thead>
                    <tr className="text-left opacity-70">
                      <th className="pr-3">vs.</th><th className="pr-3">AC</th>
                      <th className="pr-3">Hit %</th><th>Dmg/round</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.tiers.map((tier) => (
                      <tr key={tier.tier}>
                        <td className="pr-3">{tier.tier}</td>
                        <td className="pr-3">{tier.ac}</td>
                        <td className="pr-3">
                          {tier.attacks.length > 0 && tier.attacks[0].hit_chance !== null
                            ? `${Math.round(tier.attacks[0].hit_chance * 100)}%` : '—'}
                        </td>
                        <td>{tier.total_dpr}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {entry.special_abilities.length > 0 && (
                  <p className="mt-2 opacity-80">
                    Special (not in the math): {entry.special_abilities.join(', ')}
                  </p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

Note the metrics table shows the first attack's hit % per tier plus total DPR across all attacks — with multi-attack monsters the per-attack breakdown is available in `tier.attacks` if you want to render it; the total is the number that matters.

- [ ] **Step 3: Wire navigation**

In `frontend/src/components/NavRail.tsx`, add to the nav items array (line ~21, alongside existing entries) using a lucide icon already available in the installed `lucide-react` (use `Skull`):

```tsx
{ id: 'bestiary', label: 'Bestiary', icon: Skull },
```

(and add `Skull` to the existing `lucide-react` import).

In `frontend/src/App.tsx`: `import { Bestiary } from './pages/Bestiary';` and add a branch to the existing `activeView` conditional chain rendering `<Bestiary />` when `activeView === 'bestiary'`, matching exactly how `gallery`/`campaigns` are rendered.

- [ ] **Step 4: Type-check**

From `frontend/`: `npx tsc -b`
Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/monsters.ts frontend/src/pages/Bestiary.tsx frontend/src/components/NavRail.tsx frontend/src/App.tsx
git commit -m "feat(bestiary): Bestiary page - filters, metrics, encounter rolls, review mode"
```

---

### Task 10: Full verification

**Files:** none new.

- [ ] **Step 1: Full backend suite**

From `backend/`: `python -m pytest`
Expected: all bestiary tests pass; only the 7 pre-existing baseline failures remain. Record the counts.

- [ ] **Step 2: Frontend type-check**

From `frontend/`: `npx tsc -b`
Expected: zero errors.

- [ ] **Step 3: Commit any stragglers and stop**

```bash
git status --short
```

If clean besides intentional changes, the branch is ready. Integration (merge/PR) is decided with the user via superpowers:finishing-a-development-branch — do not merge unprompted.

**Manual e2e (user-driven, post-merge):** point extraction at Dungeon Denizens 2 (DCC profile) via `POST /api/v1/monsters/extract/{product_id}`, review entries in the Bestiary page's pending view, confirm a handful, and roll a wilderness table. The worker must be restarted only if it predates the new handler — coordinate with the user before touching the worker (per project convention).
