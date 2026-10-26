# Codex Reclassification: Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the seven `/code-review high` findings on `feat/codex-reclassification` that matter before the branch is pushed. One of them is a regression the final-review fix pass introduced.

**Architecture:** Product types are made canonical in one place, a SQLAlchemy `@validates("product_type")` on `Product`, instead of in each writer. Image free text that would map to a non-map type stays as written, so the Codex image guard and the image reset still recognise it. Everything else is a local guard in the classification CLI path: apply, collect, export, and the identification excerpt.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, SQLite, pytest + pytest-asyncio (`asyncio_mode = "auto"`).

**Spec:** `docs/superpowers/specs/2026-10-25-codex-reclassification-design.md` (unchanged), together with the finished plan `docs/superpowers/plans/2026-10-25-codex-reclassification.md` and its ledger `.superpowers/sdd/2026-10-25-codex-reclassification/progress.md`. Read the ledger's `Ruling:` and `Final:` lines first: they record the decisions this plan builds on.

## Where things stand (2026-10-25)

- **The branch:** `feat/codex-reclassification`, 21 commits on top of main (merge-base `2369ba7`, HEAD `96ea90e`). It is not pushed and has no PR.
- **Real data already processed:**
  - The `full` run was collected: 7,327 results, 0 errors.
  - `apply --run full` wrote 6,568 products.
  - The live export sent 5,669 items to Codex: 5,665 changed, 4 protected, all stamped.
  - `vocab-migrate` mapped 12,434 products.
- **Do not re-run the live export or `submit`.** Nothing in this plan needs the Claude API or a Codex write. Task 2 is the only one that touches the live Grimoire database, and only when Michael runs it.
- **Baseline:** from `backend/`, `C:/Users/mkemi/miniconda3/python.exe -m pytest tests -q -p no:cacheprovider` gives 772 passed and 1 failure: `tests/api/test_browse.py::test_browse_falls_back_when_home_is_unavailable`, which predates the branch. Re-measure before Task 1; don't trust this number.

## Global Constraints

- The Codex enum, from `grimoire/services/classification/enum.py`: `adventure, sourcebook, supplement, bestiary, tools, magazine, core_rulebook, setting, character_options, gm_tools, map, zine, screen, other`.
- Owner rulings:
  - Every periodical is `zine`; `magazine` is unused.
  - Supplement-vs-gm_tools ties go to `gm_tools`.
  - `core_rules` is never sent to Codex.
- Levels are whole numbers 0–40. 0 is real. A half or inverted range is no range (spec §5).
- **How to work:**
  - Run tests with the miniconda interpreter from `backend/`, not `.venv`.
  - Execute inline, not with per-task subagents (owner preference: subagents burn the weekly limit).
  - Commit only as the steps say.
  - Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Before the push: run `/code-review high` over the branch again (AGENTS.md), and fix or explain its findings.
- The app is local-only. No production hardening.
- Don't press "Sync all" in Grimoire (spec, Phase C hazard).

## Review Focus

1. **A legacy row read from the database** ("Supplement" stored before this branch) must not change just because it was loaded. Validators fire on assignment only. The Task 1 test `test_loading_a_legacy_type_does_not_change_it` pins this.
2. **A person typing "Adventure" or "core_rules" into an edit form** stores `adventure` / `core_rulebook`. Typing "Token" stores "Token". The Task 1 test `test_validator_canonicalises_every_writer` pins this.
3. **Codex sync copying Codex's `core_rules` into Grimoire** (`queue_processor.py:724`) must store `core_rulebook`. This is covered by the same validator test (assignment path).
4. **A reviewed CSV where only `max_new` is filled** (Codex had 1–5, the new value is 1–3) is a valid row, not a half range. Validation combines each blank `*_new` with its `*_old`. The Task 4 test `test_read_reviewed_validates_combined_range` pins this.
5. **Re-sending a CSV that was already sent live:** Codex answers `unchanged`. The rows are re-stamped `unchanged`, and the earlier `changed` stamp is overwritten. That's acceptable: Codex's Revision log is the record of the write. The Task 4 test `test_live_send_stamps_each_chunk` pins the stamping.

---

### Task 1: One canonical product_type rule on the model

Findings 2 and 3, and the `core_rules`/`magazine` halves of findings 8 and 9.

**The problem:**
- Text extraction (`metadata_extractor.apply_metadata_to_product`, run on every extraction with `overwrite=False`) fills empty types with "Core Rulebook", "GM Tools" and so on.
- The bulk image route (`bulk.py:264`) writes tag names ("Map", "Token").
- The final-review fix made image detection store Token → `tools` and Stock Art → `other`. After "reset image classification" clears the image flag, such a product keeps a type the Codex guard no longer recognises.

**Files:**
- Modify: `backend/grimoire/services/classification/enum.py`. Add `IMAGE_PRODUCT_TYPES` (moved here) and `canonical_product_type`, and add vocab entries.
- Modify: `backend/grimoire/services/codex_eligibility.py`. Import `IMAGE_PRODUCT_TYPES` from enum.py; it must remain importable from here (`test_codex_eligibility.py` uses it).
- Modify: `backend/grimoire/models/product.py`. Add `@validates("product_type")`.
- Modify: `backend/grimoire/api/routes/ai.py:53-56,69,253`. Delete `_enum_type` and assign the value directly.
- Modify: `backend/grimoire/services/queue_processor.py:199-210,811`.
  - `image_product_type` keeps its empty-or-image-type guard but returns the label as given (the validator canonicalises it).
  - Line 811 assigns `product_type` directly.
- Modify: `backend/grimoire/services/classification/apply.py`. The `kept_image_type` branch of `apply_vocab_migration` drops its `not product.is_image_content` condition: image free text is now kept whether or not the product is flagged, the same rule as the validator. Update `test_vocab_migration_keeps_image_free_text_without_image_flag` so the flagged "Token" also stays "Token" and `kept_image_type == 2`; rename it `test_vocab_migration_keeps_image_free_text`.
- Test: `backend/tests/models/test_product_type_validator.py` (new), plus updated existing tests (see Step 4).

**Interfaces:**
- Produces `IMAGE_PRODUCT_TYPES: frozenset[str]` in `enum.py`: the same nine lower-case values `codex_eligibility.py` holds today.
- Produces `canonical_product_type(value: str | None) -> str | None` in `enum.py`. The rules, in order:
  1. `None` or blank returns the value unchanged.
  2. If the lower-cased, stripped value is in `IMAGE_PRODUCT_TYPES` and `normalize_free_text(value) != "map"`, return the value as given.
  3. Otherwise return `normalize_free_text(value) or value`.
- `enum.py` must keep **no imports from `grimoire`**, because `models/product.py` imports it and anything else would be a cycle.
- `Product` gains `@validates("product_type")`, which returns `canonical_product_type(value)`.
- New `VOCAB_MAP` entries:
  - `"core_rules"` → `core_rulebook`. This reverses the Task 8 ruling. The reviewer called it strictly better, and Codex refuses `core_rules` either way.
  - `"Module"`, `"One-Shot"`, `"One Shot"` → `adventure`. These are the old sync aliases that were lost.

- [ ] **Step 1: Write the failing tests** in `tests/models/test_product_type_validator.py`:

```python
@pytest.mark.parametrize("given, stored", [
    ("Adventure", "adventure"), ("Core Rulebook", "core_rulebook"), ("core_rules", "core_rulebook"),
    ("Magazine", "zine"), ("magazine", "zine"), ("Module", "adventure"), ("One-Shot", "adventure"),
    ("Map", "map"), ("Art/Maps", "map"),
    ("Token", "Token"), ("Stock Art", "Stock Art"), ("Portrait", "Portrait"),   # image free text kept
    ("Anthology", "Anthology"), (None, None), ("", ""),
])
def test_validator_canonicalises_every_writer(given, stored):
    assert Product(file_path="/t/x.pdf", file_name="x.pdf", file_size=1, file_hash="x",
                   product_type=given).product_type == stored

async def test_loading_a_legacy_type_does_not_change_it(db):
    # insert a product, then UPDATE product_type='Supplement' with a Core update() statement
    # (validators do not fire on it), expire, re-select: product_type == "Supplement"

async def test_image_detection_label_survives_reset_as_an_image_type(db):
    # a product with image_product_type(None, "Token") assigned and is_image_content=True;
    # POST /api/v1/library/maintenance/reset-image-classification → product_type is None
```

- [ ] **Step 2: Run to verify they fail**, from `backend/`: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/models/test_product_type_validator.py -q -p no:cacheprovider`. Expected: FAIL. The cases fail on the values the validator should change ("Adventure" stays "Adventure"); `core_rules`/`Module` fail because there's no vocab entry; the reset test fails because the product holds `tools`.

- [ ] **Step 3: Implement** the Interfaces above.

- [ ] **Step 4: Fix the tests the validator changes.** Run the whole suite. Tests that build a `Product` with legacy free text and then assert that text survives will now see it canonicalised. Known cases in `tests/services/classification/test_apply.py`:
  - `_product(..., "Supplement")`, with the assertion `bad.product_type == "Supplement"`
  - the sibling test's `"Supplement"`
  - the vocab-migration tests' `"Supplement"` / `"Adventure"`

  Give those a helper `_legacy_type(db, product, value)` that writes the value with `update(Product).where(Product.id == product.id).values(product_type=value)` and then `await db.refresh(product)`, so the test still exercises a pre-branch row.
  - Tests that only build fixtures (e.g. `test_codex_eligibility.py` with "Map" / "Art/Maps") should still pass: both become `map`, which is in `IMAGE_PRODUCT_TYPES`.
  - Change no test's meaning, only how it creates a legacy row. Ledger each changed test.

- [ ] **Step 5: Run the whole suite.** Expected: the baseline plus the new tests, with only the pre-existing `test_browse` failure.

- [ ] **Step 6: Commit**: `fix(products): one canonical product_type rule on the model; image free text kept`

---

### Task 2: Put back the image labels the vocab migration replaced

The second half of finding 2, for existing data. `vocab-migrate` mapped 75 image-flagged products (Stock Art 40, Token 21, Portrait 14) to `other` / `tools`. "Reset image classification" won't clear those. This task restores the original label wherever nobody has changed the product since.

**Files:**
- Modify: `backend/grimoire/services/classification/apply.py`. Add `restore_image_types`.
- Modify: `backend/scripts/classify.py`. Add `restore-image-types [--dry-run]`.
- Test: `backend/tests/services/classification/test_apply.py`.

**Interfaces:**
- Consumes `IMAGE_PRODUCT_TYPES` (Task 1) and `VOCAB_RUN = "vocab-migration"` (already in `apply.py`).
- Produces `async restore_image_types(db, dry_run: bool = False) -> int`. It returns the number of products restored.
- **Which rows qualify:** `vocab-migration` result rows whose `product_type_old.strip().lower()` is in `IMAGE_PRODUCT_TYPES`, whose `product_type_new != "map"`, and whose product still holds `product_type_new`.
- **What it does to each:** sets `product.product_type = product_type_old`, and sets the result row's `product_type_new = product_type_old`, so the record matches the product.
- It commits unless `dry_run`.

- [ ] **Step 1: Write the failing tests:**

```python
async def test_restore_image_types_puts_back_the_label(db): ...         # vocab row Token→tools, product holds tools → "Token"; returns 1
async def test_restore_image_types_skips_hand_edits_and_maps(db): ...   # product changed to "adventure" since → untouched; Map→map row → untouched
async def test_restore_image_types_dry_run_writes_nothing(db): ...
```

- [ ] **Step 2: Run to verify they fail.** Expected: ImportError on `restore_image_types`.
- [ ] **Step 3: Implement.** The CLI prints `DRY RUN: would restore N` / `restored N`.
- [ ] **Step 4: Run the classification tests**: `C:/Users/mkemi/miniconda3/python.exe -m pytest tests/services/classification -q -p no:cacheprovider`. Expected: all pass.
- [ ] **Step 5: Real dry run** against the live database: `python scripts/classify.py restore-image-types --dry-run`. Expected: about 75. Don't run it live; that's Michael's call, so report the number.
- [ ] **Step 6: Commit**: `feat(classification): restore image labels the vocab migration replaced`

---

### Task 3: Collect and apply never write a missing or `magazine` result

Findings 6 and 9.
- **The missing result:** `submit_run` creates a row per item with null new values, and `collect_run` fills only rows whose `custom_id` came back. A missing result keeps `error=None` and a null type, and `apply_run` would then blank that product's type.
- **The `magazine` case:** the output schema allows `magazine`, which `_store` stores as is.

**Files:**
- Modify: `backend/grimoire/services/classification/batch.py:178` (`_store`) and `collect_run`.
- Modify: `backend/grimoire/services/classification/apply.py:85` (`apply_run`, `ApplyReport`).
- Test: `backend/tests/services/classification/test_batch.py`, `test_apply.py`.

**Interfaces:**
- `_store` sets `row.product_type_new = normalize_free_text(out.product_type)`, which turns `magazine` into `zine`.
- After storing a batch's results, `collect_run` marks every row of that batch still lacking a result with `error = "no result returned"`. This only happens once the batch has ended.
- `ApplyReport` gains `skipped_no_result: int = 0`. `apply_run` counts and skips a row whose `product_type_new is None`, without stamping `applied_at`. This check comes after the `error` check.
- Update the `apply` CLI print line to include the new counter.

- [ ] **Step 1: Write the failing tests:**

```python
async def test_collect_maps_magazine_to_zine(db): ...                 # fake batch result product_type "magazine" → row.product_type_new == "zine"
async def test_collect_marks_rows_with_no_result(db): ...             # 2 items submitted, the ended batch returns 1 → other row.error == "no result returned"
async def test_apply_skips_rows_without_a_new_type(db): ...           # collected run, row product_type_new None, no error → product type unchanged, applied_at None, skipped_no_result == 1
```

  Use `FakeBatches` from `test_batch.py`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/services/classification`. Expected: all pass.
- [ ] **Step 5: Commit**: `fix(classification): missing results are errors; magazine stored as zine; apply never writes a null type`

---

### Task 4: The live export checks first, validates the reviewed CSV, and stamps as it goes

Findings 1 and 7.

**Files:**
- Modify: `backend/grimoire/services/classification/export.py`. Make `_collected_run` public as `collected_run`, add validation in `read_reviewed`, and add `send_and_stamp`.
- Modify: `backend/scripts/classify.py` (`cmd_export`, live branch).
- Test: `backend/tests/services/classification/test_export.py`.

**Interfaces:**
- Rename `_collected_run` → `collected_run(db, run_name) -> ClassificationRun`, and update both callers in `export.py`.
- **`read_reviewed(path) -> list[ExportItem]`** raises `ValueError` listing every bad row (`slug: reason`, one per line) and returns nothing when any row is bad. For a row with `send` = yes:
  - **Type:** a non-blank `type_new` goes through `normalize_free_text`. It is bad if the result isn't in `CODEX_PRODUCT_TYPES`, or is `magazine` / `core_rules`.
  - **Levels:** if either `min_new` or `max_new` is non-blank, combine `(min_new or min_old, max_new or max_old)`. It is bad unless both ends are present, are whole numbers 0–40, and min ≤ max. Only the non-blank `*_new` fields are sent, as today.
- **`async send_and_stamp(db, run_name, items, token, client=None) -> dict[str, dict]`** does the work in this order:
  1. Calls `collected_run` first, so it raises before anything is sent.
  2. Sends in `CHUNK`s through `send_items(chunk, token, dry_run=False, client=client)`.
  3. Calls `stamp_exported` after each chunk; it already commits.
  4. Returns all outcomes.
  5. On an exception from a later chunk it re-raises, with the earlier chunks already stamped and committed.
- The live branch of `cmd_export` calls `send_and_stamp` instead of `send_items` + `stamp_exported`. On an exception it prints `sent and recorded N items before the failure; re-running is safe (Codex answers unchanged)` and exits non-zero.

- [ ] **Step 1: Write the failing tests:**

```python
def test_read_reviewed_rejects_bad_type_and_ranges(tmp_path): ...
    # three send=yes rows: (a) type_new "adventrue";
    # (b) min_new 7, max_new 3 (inverted);
    # (c) min_old "", min_new "", max_old "", max_new 5 (half: no min anywhere)
    # → ValueError whose message names all three slugs

def test_read_reviewed_validates_combined_range(tmp_path): ...
    # min_old 1, max_old 5, min_new "", max_new 3 → accepted; fields == {"level_range_max": 3}

async def test_live_send_checks_the_run_before_sending(db): ...
    # no run named "full" → ValueError; the MockTransport saw 0 requests

async def test_live_send_stamps_each_chunk(db): ...
    # 150 items, a MockTransport that answers 500 on the 2nd POST → raises;
    # the first 100 rows have exported_status "changed", the rest None
```

  Reuse `_run`, `_item` and `_codex` from `test_export.py`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/services/classification`. Expected: all pass, including `test_cli_live_requires_from_and_yes`.
- [ ] **Step 5: Commit**: `fix(export): check the run before a live send, validate the reviewed CSV, stamp per chunk`

---

### Task 5: Build the identification excerpt off the event loop

Finding 10. `identify_product` (`ai_identifier.py:345`) and `suggest_tags` (`:534`) run `build_excerpt` synchronously over the whole book. That's the event-loop blocking pattern PR #7 removed, and it stalls the API on a large book.

**Files:**
- Modify: `backend/grimoire/processors/ai_identifier.py:345,534`.
- Test: `backend/tests/processors/test_identification_prompt.py`.

**Interfaces:**
- Both sites become `(await asyncio.to_thread(build_excerpt, {"markdown": text}, {"filename": ...})).text`, with the same header values as today. `asyncio` is already imported.

- [ ] **Step 1: Write the failing test** `test_excerpt_is_built_off_the_event_loop`. Monkeypatch `ai_identifier.build_excerpt` with a wrapper that records `threading.current_thread()` and calls the real one. Reuse `_sent_text` from the same file. Assert the recorded thread is not `threading.main_thread()`.
- [ ] **Step 2: Run to verify it fails.** Expected: the recorded thread is the main thread.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/processors/test_identification_prompt.py`, then the whole suite. Expected: baseline plus the new tests, with only the `test_browse` failure.
- [ ] **Step 5: Commit**: `fix(identify): build the excerpt in a worker thread`

---

## After the tasks

1. **Whole-branch review.** Run `/code-review high` again over `main...HEAD` (AGENTS.md). Fix the findings that matter or ledger why they stay.
2. **Ledger, then PR.** Update the ledger, then offer the PR. The PR body ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Don't push without Michael's go-ahead.
3. **Owner's data commands, after review.** Report the Task 2 dry-run number. Michael then runs `python scripts/classify.py restore-image-types` himself.

## Deliberately not in this plan (deferred, with reasons)

- **`submit_run` multi-batch partial failure** (review finding 4). This only happens on runs over 10,000 requests; none is planned. If one is: commit the run row before the first `batches.create`, and persist each `batch_id` as it's created.
- **With several Codex products on one file, an arbitrary result wins in Grimoire** (finding 5). This is known and documented. The 36 shared files include the promo PDF matched by 11 map packs. Codex gets each product's own result, so only Grimoire's copy is affected.
- **Final-review minors still open:**
  - The prompt has no rule for "begin at Nth level, should reach Mth". The live data read it three ways.
  - `cost_usd` ignores cache pricing.
  - A non-Latin title that normalises to "" can title-match the wrong folder (0 rows today).
  - `estimate_tokens` runs about 30% low.
