# Codex Reclassification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify every Codex product's `product_type` and level range from the matching Grimoire PDF, measure accuracy on a hand-labelled pilot, and push the approved corrections to Codex through its override endpoint.

**Architecture:** A `grimoire.services.classification` package holds the pipeline as pure-ish functions over SQLAlchemy sessions (snapshot → match → excerpt → batch → apply → export), three new tables record the Codex snapshot and every decision, and a single CLI `backend/scripts/classify.py` exposes each stage as a subcommand. Nothing runs automatically; Michael drives the stages by hand and the live export reads back a CSV he has reviewed.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async + aiosqlite, pydantic 2, `anthropic` SDK (Message Batches, structured outputs), `rapidfuzz`, `httpx` for Codex, pytest + pytest-asyncio (`asyncio_mode = "auto"`), React + TypeScript for the label change.

**Spec:** `docs/superpowers/specs/2026-10-25-codex-reclassification-design.md`

## Global Constraints

- Codex enum, exactly: `adventure, sourcebook, supplement, bestiary, tools, magazine, core_rulebook, setting, character_options, gm_tools, map, zine, screen, other`. Never emit `core_rules`.
- Levels are integers 0–40; 0 is real. Written and compared with `is not None`, never truthiness. A half range (one side null) or `min > max` is treated as no range.
- Excerpt cap about 4,000 tokens, estimated as `len(text) // 4`. Head is trimmed before windows are.
- Models: `claude-sonnet-5-5` and `claude-opus-5-5`, `output_config.effort` set explicitly (`medium` default). No `thinking` parameter, no `temperature`, no forced `tool_choice`.
- Batch prices per MTok used for `cost_usd`: Opus 5.5 input 2.00 / output 10.00; Sonnet 5.5 input 1.00 / output 5.00.
- Codex: `POST https://codex-api.livetorole.com/api/v1/classification/`, header `Authorization: Token <key>`, a real `User-Agent` (Cloudflare 403s Python's default), at most 100 items per request, `dry_run` true by default, null never sent.
- Settings values in the `settings` table are JSON-encoded strings: read with `json.loads`.
- Test runner: from `backend/`, `python -m pytest` (the miniconda interpreter, not `.venv`). Frontend gate is `tsc -b` from `frontend/`.
- Branch: `feat/codex-reclassification`. Commit after every task.

## Review Focus

1. A Codex title with curly quotes, ampersands, or a trailing `(English)` against a folder with underscores: normalisation must make them equal. Test in Task 3.
2. A 5e book whose first six "level" hits are spell levels: the windows must not be spent on them. Test in Task 4 (negative context filter).
3. A batch result whose text is not valid JSON or whose `stop_reason` is `max_tokens`/`refusal`: recorded as an error row, the rest of the batch still stored. Test in Task 6.
4. A Codex product deleted or merged since the snapshot: `not_found` lands in the report, nothing crashes. Test in Task 9.
5. `apply` run twice: the second run changes nothing (rows with `applied_at` are skipped). Test in Task 8.

---

## File structure

```
backend/grimoire/models/classification.py           CodexProduct, ClassificationRun, ClassificationResult
backend/grimoire/services/classification/
    __init__.py
    enum.py          CODEX_PRODUCT_TYPES, VOCAB_MAP, normalize_free_text
    snapshot.py      SNAPSHOT_SQL, dump_codex, import_snapshot
    matching.py      normalize, product_folder, choose_file, match_all
    excerpt.py       LEVEL_PATTERNS, Excerpt, build_excerpt, build_description_excerpt
    prompt.py        SYSTEM_PROMPT, OUTPUT_SCHEMA, ClassificationOutput, build_request
    batch.py         anthropic_api_key, submit_run, collect_run, cost_usd
    pilot.py         KNOWN_WRONG_SLUGS, select_pilot, write_pilot_sheet, score_pilot
    apply.py         apply_run, apply_vocab_migration
    export.py        build_items, send_items, write_report, read_reviewed
backend/scripts/classify.py                          CLI, one subcommand per stage
backend/tests/services/classification/test_*.py
frontend/src/lib/productType.ts                     PRODUCT_TYPE_LABELS, productTypeLabel
```

Each service module gets its own test file of the same name. The CLI grows one subcommand per task; Task 2 creates it.

---

### Task 1: Models, enum, vocabulary table

**Files:**
- Create: `backend/grimoire/models/classification.py`
- Create: `backend/grimoire/services/classification/__init__.py` (empty)
- Create: `backend/grimoire/services/classification/enum.py`
- Modify: `backend/grimoire/models/__init__.py` (import + `__all__`)
- Modify: `backend/requirements.txt`, `backend/pyproject.toml` (add `anthropic>=1.0`, `rapidfuzz>=3.0`)
- Test: `backend/tests/services/classification/test_enum.py`, `backend/tests/models/test_classification_models.py`

**Interfaces:**
- Produces `CODEX_PRODUCT_TYPES: tuple[str, ...]` (14 values, spec order), `VOCAB_MAP: dict[str, str]` (spec Phase D table, keys as written in Grimoire), `normalize_free_text(value: str | None) -> str | None` (case-insensitive, stripped; returns the enum value, or the value itself if it already is one, else `None`).
- Produces models, all in `classification.py`:
  - `CodexProduct` table `codex_products`: `id: str` (uuid, PK), `slug`, `title`, `publisher: str | None`, `product_type: str | None`, `level_range_min: int | None`, `level_range_max: int | None`, `dtrpg_id: str | None`, `page_count: int | None`, `description: str | None`, `grimoire_product_id: int | None` (FK products.id, nullable), `match_method: str` (default `"none"`), `match_score: float | None`, `in_pilot: bool` (default False), `imported_at: datetime`.
  - `ClassificationRun` table `classification_runs`: `id: int` PK, `name: str` unique, `model: str`, `effort: str`, `batch_id: str | None`, `status: str` (`created|submitted|ended|collected`), `request_count: int`, `submitted_at`, `completed_at`, `input_tokens: int`, `output_tokens: int`, `cost_usd: float`.
  - `ClassificationResult` table `classification_results`: `id` PK, `run_id` FK, `product_id: int | None` FK products, `codex_product_id: str | None` FK codex_products, `source: str` (`pdf|description|vocab`), `product_type_old`, `product_type_new`, `level_min_old`, `level_min_new`, `level_max_old`, `level_max_new`, `confidence: float | None`, `type_evidence: str | None`, `level_evidence: str | None`, `notes: str | None`, `raw_response: str | None`, `error: str | None`, `applied_at: datetime | None`, `exported_status: str | None`, `exported_at: datetime | None`, `created_at`. Unique on `(run_id, codex_product_id)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/services/classification/test_enum.py
from grimoire.services.classification.enum import CODEX_PRODUCT_TYPES, VOCAB_MAP, normalize_free_text

def test_enum_has_fourteen_values_and_no_core_rules():
    assert len(CODEX_PRODUCT_TYPES) == 14
    assert "core_rules" not in CODEX_PRODUCT_TYPES
    assert "core_rulebook" in CODEX_PRODUCT_TYPES

def test_vocab_map_targets_are_enum_values():
    assert set(VOCAB_MAP.values()) <= set(CODEX_PRODUCT_TYPES)

def test_normalize_free_text():
    assert normalize_free_text("Core Rulebook") == "core_rulebook"
    assert normalize_free_text("  quick start guide ") == "core_rulebook"
    assert normalize_free_text("adventure") == "adventure"
    assert normalize_free_text("Anthology") is None
    assert normalize_free_text(None) is None
```

```python
# tests/models/test_classification_models.py
async def test_tables_exist_and_roundtrip(db):
    cp = CodexProduct(id="0f1e...", slug="x", title="X")
    run = ClassificationRun(name="t", model="claude-sonnet-5-5", effort="medium")
    db.add_all([cp, run]); await db.flush()
    r = ClassificationResult(run_id=run.id, codex_product_id=cp.id, source="pdf", level_min_new=0)
    db.add(r); await db.flush()
    assert cp.match_method == "none" and cp.in_pilot is False
    assert r.level_min_new == 0
```

- [ ] **Step 2: Run them to verify they fail** — `python -m pytest tests/services/classification tests/models/test_classification_models.py -q`. Expected: ImportError.
- [ ] **Step 3: Implement `enum.py` and `models/classification.py`; register the models in `models/__init__.py`; add the two dependencies and install them** (`pip install anthropic rapidfuzz` in the miniconda env).
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Commit** — `feat(classification): models, Codex enum and vocabulary table`.

---

### Task 2: Codex snapshot import and the CLI skeleton

**Files:**
- Create: `backend/grimoire/services/classification/snapshot.py`
- Create: `backend/scripts/classify.py`
- Test: `backend/tests/services/classification/test_snapshot.py`, fixture `backend/tests/fixtures/classification/codex_snapshot.csv` (6 rows: one with a description, one with `other`, one with levels, one with an empty publisher, two sharing a publisher)

**Interfaces:**
- Produces `SNAPSHOT_SQL: str` (the `\copy` select: `p.id, p.slug, p.title, pub.name as publisher, p.product_type, p.level_range_min, p.level_range_max, p.dtrpg_id, p.page_count, p.description` from `catalog_product p left join catalog_publisher pub on pub.id = p.publisher_id order by p.slug`).
- Produces `dump_codex(out_path: Path) -> int` (reads `DATABASE_PUBLIC_URL` from `railway variables --service Postgres --kv`, runs `psql "$URL" -c "\copy (...) to '<out>' csv header"`, returns row count; `cwd` must be the grimoire repo root because the railway link is per-directory).
- Produces `async import_snapshot(db, csv_path: Path) -> int` (upsert by `id`; keeps `grimoire_product_id`, `match_method`, `match_score`, `in_pilot` on re-import; empty strings become `None`; returns rows imported).
- CLI: `python scripts/classify.py dump-codex [--out path]` and `import-codex <csv>`. The script builds its own `async_sessionmaker` from `grimoire.config.settings.database_url` the way `scripts/backfill_dcc_levels.py` does.

- [ ] **Step 1: Write the failing tests**

```python
async def test_import_snapshot_upserts_and_preserves_match(db, snapshot_csv):
    assert await import_snapshot(db, snapshot_csv) == 6
    cp = await db.get(CodexProduct, "<id of the levels row>")
    assert (cp.level_range_min, cp.level_range_max) == (1, 3)
    cp.grimoire_product_id = 42; cp.match_method = "folder"; await db.flush()
    await import_snapshot(db, snapshot_csv)
    cp = await db.get(CodexProduct, cp.id)
    assert cp.grimoire_product_id == 42 and cp.match_method == "folder"

async def test_import_blank_publisher_is_none(db, snapshot_csv): ...

def test_snapshot_sql_selects_description():
    assert "p.description" in SNAPSHOT_SQL and "catalog_publisher" in SNAPSHOT_SQL
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement `snapshot.py` and the CLI skeleton with the two subcommands.** `dump_codex` uses `subprocess.run` with `check=True`; it never prints the URL.
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Real check** — `python scripts/classify.py dump-codex` then `import-codex data/classification/codex_snapshot.csv`. Expected: `7327 rows`.
- [ ] **Step 6: Commit** — `feat(classification): Codex snapshot dump and import`.

---

### Task 3: Matching Codex products to Grimoire files

**Files:**
- Create: `backend/grimoire/services/classification/matching.py`
- Modify: `backend/scripts/classify.py` (add `match [--report path]`)
- Test: `backend/tests/services/classification/test_matching.py`

**Interfaces:**
- Produces `normalize(s: str | None) -> str` (NFKD → ASCII, lowercase, every run of non-alphanumerics → one space, stripped; `None` → `""`).
- Produces `product_folder(file_path: str) -> tuple[str, str] | None` (publisher folder, product folder) when the path is `<drive>\Drivethrurpg\<pub>\<title>\<file>` (case-insensitive on `Drivethrurpg`), else `None`.
- Produces `choose_file(candidates: list[Product]) -> Product | None`: drop `is_duplicate`, `is_missing`, `text_unextractable`; prefer `text_extracted`; then largest `page_count`; then largest `file_size`.
- Produces `@dataclass MatchReport(folder: int, title: int, fuzzy: int, none: int, unmatched: list[tuple[str, str, str]])` and `async match_all(db, fuzzy_threshold: int = 90) -> MatchReport`. Order per spec §2. Fuzzy uses `rapidfuzz.fuzz.token_set_ratio` on the normalised Codex title against each product folder and file stem, restricted to the same normalised publisher when Codex has one; accepted at `>= fuzzy_threshold`; ties broken by higher score then `choose_file`. Writes `grimoire_product_id`, `match_method`, `match_score`.

- [ ] **Step 1: Write the failing tests**

```python
def test_normalize_strips_punctuation_and_unicode():
    assert normalize("d30 Collection of Height & Weight Table (English)") == normalize("d30_Collection_of_Height___Weight_Table__English_")
    assert normalize("Gary Gygax’s The Hermit") == normalize("Gary_Gygax's_The_Hermit")

def test_product_folder_parses_drivethru_layout():
    assert product_folder(r"D:\Drivethrurpg\Frog God Games\City of Brass\cob.pdf") == ("Frog God Games", "City of Brass")
    assert product_folder(r"E:\Other\book.pdf") is None

def test_choose_file_prefers_extracted_then_pages_then_size(): ...   # includes a duplicate and an unextractable that must lose

async def test_match_all_methods(db):
    # 3 Grimoire products: one exact folder match, one title-only (publisher differs), one fuzzy ("1008573-BeachEncounters" vs file stem "BeachEncounters")
    # 1 Codex row with no counterpart
    report = await match_all(db)
    assert (report.folder, report.title, report.fuzzy, report.none) == (1, 1, 1, 1)

async def test_fuzzy_has_no_false_positive_on_decoys(db):
    # same publisher, titles "Tomb of Rakoss" vs "Tomb of Horrors": must stay none
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement `matching.py` and the `match` subcommand.** The subcommand prints the four counts and writes the unmatched list to `data/classification/unmatched.csv` (slug, title, publisher).
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Real check** — `python scripts/classify.py match`. Expected: folder ≈ 6,500, title ≈ 70, fuzzy > 0, none < 751. Read 20 fuzzy rows by eye (`select slug, title, match_score from codex_products where match_method='fuzzy' order by match_score limit 20`). If any is wrong, raise the threshold and re-run.
- [ ] **Step 6: Commit** — `feat(classification): match Codex products to Grimoire files by folder, title, fuzzy`.

---

### Task 4: Excerpt builder

**Files:**
- Create: `backend/grimoire/services/classification/excerpt.py`
- Modify: `backend/scripts/classify.py` (add `excerpt <codex-slug>` which prints the excerpt, for eyeballing)
- Test: `backend/tests/services/classification/test_excerpt.py`

**Interfaces:**
- Produces `estimate_tokens(text: str) -> int` (`len(text) // 4`).
- Produces `LEVEL_PATTERNS: list[re.Pattern]` covering: `levels? \d+(\s*(-|–|to|through)\s*\d+)?`, `\d+(st|nd|rd|th)[ -]level`, `0-level`, `level 0`, `funnel`, `character levels?`, `characters? of level`, `tiers? \d`. Case-insensitive. A match is discarded when the 40 characters either side contain `spell`, `caster`, `dungeon level`, or `level \d+ (warlock|wizard|cleric|druid|sorcerer|bard|paladin|ranger)`.
- Produces `@dataclass Excerpt(text: str, source: str, windows: int, unpaged: bool, tokens: int)`.
- Produces `build_excerpt(text_json: dict, header: dict[str, str], head_tokens: int = 2500, window_tokens: int = 150, max_windows: int = 6, max_tokens: int = 4000) -> Excerpt`. Layout: a `# Document` block rendering the header as `key: value` lines, then `# Opening pages` with each page as `--- page N ---` + markdown, then `# Passages mentioning levels` with `--- page N ---` (or `--- offset N ---` when unpaged) + window. Overlapping windows are merged; earliest first. When `pages` is absent, use `markdown` and set `unpaged=True`. Trim order when over `max_tokens`: head pages from the end, then drop windows from the last.
- Produces `build_description_excerpt(codex: CodexProduct) -> Excerpt` (`source="description"`; header title, publisher, page count; body is the description).

- [ ] **Step 1: Write the failing tests**

```python
def test_head_stops_at_budget_and_tags_pages(): ...        # 20 pages of 600 chars → head holds ~16 pages, each tagged "--- page N ---"
def test_level_windows_merge_and_order(): ...               # two hits 50 chars apart on page 40 → one window, tagged page 40, after the head
def test_hard_cap_trims_head_before_windows(): ...          # tokens <= 4000 and the window from page 90 survives
def test_dcc_zero_level_matches():                          # "a 0-level funnel for 12–16 characters" → window present
def test_page_number_and_spell_level_do_not_match():        # "page 12", "3rd-level spell slots", "level 5 wizard" → zero windows
def test_unpaged_fallback_flags_and_uses_offsets(): ...     # {"markdown": "..."} only → unpaged True, "--- offset"
def test_description_excerpt_source(): ...
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement `excerpt.py` and the `excerpt` subcommand.**
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Real check** — `python scripts/classify.py excerpt the-tomb-of-rakoss` and one DCC funnel. Expected: a readable excerpt under ~16k characters with the level statement visible.
- [ ] **Step 6: Commit** — `feat(classification): excerpt builder with level windows`.

---

### Task 5: Prompt, output schema, request builder

**Files:**
- Create: `backend/grimoire/services/classification/prompt.py`
- Test: `backend/tests/services/classification/test_prompt.py`

**Interfaces:**
- Produces `SYSTEM_PROMPT: str` (fixed text; see spec §4 for what it must say). Written once, never formatted per request, so it caches.
- Produces `class ClassificationOutput(BaseModel)`: `product_type: Literal[<14>]`, `level_range_min: int | None` (0–40), `level_range_max: int | None` (0–40), `confidence: float` (0–1), `type_evidence: str`, `level_evidence: str | None`, `notes: str`. `OUTPUT_SCHEMA = ClassificationOutput.model_json_schema()` with `additionalProperties: false`.
- Produces `build_request(custom_id: str, excerpt_text: str, model: str, effort: str, max_tokens: int = 8000) -> dict` returning the Batches `Request` shape: `{"custom_id", "params": {"model", "max_tokens", "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}], "messages": [{"role": "user", "content": excerpt_text}], "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}}}`. No `thinking`, no `temperature`, no `tool_choice`.
- Produces `parse_output(text: str) -> ClassificationOutput` (`json.loads` then validate; raises `ValueError` with the raw text on failure).

- [ ] **Step 1: Write the failing tests**

```python
def test_schema_enum_is_codex_enum():
    assert set(OUTPUT_SCHEMA["properties"]["product_type"]["enum"]) == set(CODEX_PRODUCT_TYPES)
    assert OUTPUT_SCHEMA["additionalProperties"] is False

def test_system_prompt_states_the_rules():
    for needle in ("0-level", "level 0", "never infer", "core_rulebook", "page number", "spell level"):
        assert needle.lower() in SYSTEM_PROMPT.lower()
    assert "core_rules" not in SYSTEM_PROMPT.replace("core_rulebook", "")

def test_build_request_shape():
    r = build_request("cx-1", "text", "claude-opus-5-5", "medium")
    p = r["params"]
    assert p["output_config"]["format"]["type"] == "json_schema"
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in p and "temperature" not in p and "tool_choice" not in p

def test_parse_output_accepts_level_zero_and_rejects_41():
    assert parse_output('{"product_type":"adventure","level_range_min":0,"level_range_max":0,"confidence":0.9,"type_evidence":"x","level_evidence":"0-level funnel","notes":""}').level_range_min == 0
    with pytest.raises(ValueError): parse_output('{"product_type":"adventure","level_range_min":41, ...}')
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement `prompt.py`.** Seed the enum descriptions from Codex's `ProductType` choices in `codex/backend/apps/catalog/models/catalog.py` and the boundaries listed in spec §4.
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Commit** — `feat(classification): system prompt, structured output schema, batch request builder`.

---

### Task 6: Batch submit and collect

**Files:**
- Create: `backend/grimoire/services/classification/batch.py`
- Modify: `backend/scripts/classify.py` (add `submit --run NAME --model M [--effort medium] [--pilot | --all | --slugs file]` and `collect --run NAME [--wait]`)
- Test: `backend/tests/services/classification/test_batch.py` (fake client objects, no network)

**Interfaces:**
- Produces `async anthropic_api_key(db) -> str` (settings row `anthropic_api_key` via `json.loads`, else `ANTHROPIC_API_KEY`, else raise).
- Produces `BATCH_PRICES: dict[str, tuple[float, float]]` and `cost_usd(model: str, input_tokens: int, output_tokens: int) -> float`.
- Produces `@dataclass RunItem(codex_product_id: str, product_id: int | None, source: str, excerpt: Excerpt)` and `async build_items(db, *, pilot: bool = False, all_: bool = False, slugs: list[str] | None = None) -> list[RunItem]` (matched → `build_excerpt` from the chosen file's `extracted_text_path`; `match_method == "none"` → `build_description_excerpt`; header includes filename, publisher folder, product folder, page count, Codex title, Grimoire's current type and levels).
- Produces `async submit_run(db, client, name: str, model: str, effort: str, items: list[RunItem]) -> ClassificationRun`: `custom_id` is the `codex_product_id`; requests sent in chunks of up to 10,000 via `client.messages.batches.create`; one `ClassificationRun` per name, `batch_id` holds comma-joined ids; a `ClassificationResult` row is created per item at submit time with the `*_old` columns filled from the Grimoire product (or the Codex row for description-only) and `source` set.
- Produces `async collect_run(db, client, name: str) -> dict[str, int]`: for each batch id, `retrieve` until `processing_status == "ended"` (`--wait` polls every 60 s, otherwise returns `{"pending": n}`), then `results(batch_id)`; `succeeded` → `parse_output` into the result row's `*_new`, `confidence`, evidences, `notes`, `raw_response`; `stop_reason` of `max_tokens` or `refusal`, or a parse failure, → `error` filled, `*_new` left null; `errored|canceled|expired` → `error`. Sums `usage.input_tokens + cache_creation_input_tokens + cache_read_input_tokens` and `output_tokens` into the run, sets `cost_usd`, `status = "collected"`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_submit_creates_run_and_result_rows_with_old_values(db, fake_client): ...   # 2 items; fake_client.created[0].requests[0]["custom_id"] == codex id; result.product_type_old == "Supplement"
async def test_collect_stores_parsed_output_and_cost(db, fake_client): ...               # succeeded result with level 0 → level_min_new == 0; run.cost_usd == cost_usd(model, in, out)
async def test_collect_records_bad_json_and_max_tokens_as_errors(db, fake_client): ...   # 3 results: good, bad json, stop_reason max_tokens → one stored, two with error, no exception
def test_cost_usd_uses_batch_prices():
    assert cost_usd("claude-opus-5-5", 1_000_000, 100_000) == pytest.approx(3.0)
```

`fake_client` is a fixture exposing `messages.batches.create/retrieve/results` over in-memory lists, shaped like the SDK objects (`SimpleNamespace` is enough).

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement `batch.py` and the two subcommands.** `submit` prints request count, estimated input tokens, and the projected cost from `BATCH_PRICES` before sending, then sends. The real client is `anthropic.Anthropic(api_key=...)`.
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Commit** — `feat(classification): submit and collect Message Batches runs`.

---

### Task 7: Pilot selection, sheet, score

**Files:**
- Create: `backend/grimoire/services/classification/pilot.py`
- Modify: `backend/scripts/classify.py` (add `select-pilot [--n 150] [--seed 20261025]`, `pilot-sheet --runs A,B --out path`, `pilot-score --runs A,B --truth path`)
- Test: `backend/tests/services/classification/test_pilot.py`

**Interfaces:**
- Produces `KNOWN_WRONG_SLUGS: tuple[str, ...]` = `d30-collection-of-height-weight-table-english`, `d30-human-height-weight-table-english`, `d30-npc-background-generator`, `d30-quick-npc-personality-generator`, `generic-spell-effect-cards`.
- Produces `async select_pilot(db, n: int = 150, seed: int = 20261025, description_share: int = 15, floor: int = 5, weights: dict[str, float] = {"other": 2.0, "adventure": 1.5}) -> list[str]` (slugs). Always includes `KNOWN_WRONG_SLUGS` that exist; `description_share` rows from `match_method == "none"`; the rest stratified over current Codex `product_type` with the floor, remaining quota proportional × weight; seeded `random.Random`. Sets `in_pilot = True` and clears it elsewhere.
- Produces `async write_pilot_sheet(db, run_names: list[str], out: Path, excerpt_dir: Path) -> int`: one row per pilot product: `slug, title, publisher, excerpt_path, codex_type, codex_min, codex_max`, then per run `<run>_type, <run>_min, <run>_max, <run>_confidence, <run>_type_evidence, <run>_level_evidence`, then `true_type, true_min, true_max` blank. Writes each excerpt to `excerpt_dir/<slug>.md`.
- Produces `@dataclass Score(run: str, n: int, type_accuracy: float, level_exact: float, level_false_positive: float, cost_per_product: float)` and `async score_pilot(db, run_names: list[str], truth: Path) -> list[Score]`. A truth row with blank `true_type` is skipped. `level_false_positive` = share of products with blank truth levels where the model gave any level.

- [ ] **Step 1: Write the failing tests**

```python
async def test_select_pilot_includes_known_wrong_and_respects_floor_and_share(db): ...   # seed fixed; known slugs present; >=5 per type present in snapshot; exactly 15 with match_method none; len == 150; second call same seed → same slugs
async def test_pilot_sheet_columns_per_run(db, tmp_path): ...
async def test_score_pilot_computes_accuracy_and_level_fp(db, tmp_path):
    # 4 products: types 3/4 right; levels: 1 exact, 1 wrong, 1 correctly null, 1 null-in-truth-but-model-gave-level → level_false_positive == 0.5
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement `pilot.py` and the three subcommands.**
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Commit** — `feat(classification): pilot selection, label sheet and scoring`.

**Hand-off point.** After this task the pilot can run for real (see Run sequence). Tasks 8–13 do not depend on its outcome and can proceed while Michael labels.

---

### Task 8: Retire the stale sync mapping (before apply)

**Files:**
- Modify: `backend/grimoire/services/sync_service.py:42-74,101-127`
- Modify: `backend/grimoire/api/routes/library.py:623`
- Test: `backend/tests/services/test_sync_product_type.py` (new), existing `tests/services/test_codex_eligibility.py` must still pass

**Interfaces:**
- `normalize_product_type(product_type: str | None) -> str | None` keeps its name and signature. New behaviour: `None` → `None`; a value already in `CODEX_PRODUCT_TYPES` → itself; else `normalize_free_text(value)`; else `"other"`. `PRODUCT_TYPE_MAPPING` and `CODEX_PRODUCT_TYPES` in `sync_service` are deleted; the module imports the enum from `classification.enum`.
- `library.py` image-type reset tuple gains `"map"` and `"other"` is not added (it is not an image classification).

- [ ] **Step 1: Write the failing tests**

```python
def test_enum_values_pass_through_unchanged():
    for v in CODEX_PRODUCT_TYPES: assert normalize_product_type(v) == v

def test_core_rulebook_is_never_core_rules():
    assert normalize_product_type("core_rulebook") == "core_rulebook"
    assert normalize_product_type("Core Rulebook") == "core_rulebook"

def test_free_text_goes_through_vocab_then_other():
    assert normalize_product_type("Setting") == "setting"
    assert normalize_product_type("Map") == "map"
    assert normalize_product_type("Anthology") == "other"
    assert normalize_product_type(None) is None
```

- [ ] **Step 2: Run to verify they fail** (`"core_rulebook"` → `"core_rules"` today).
- [ ] **Step 3: Implement.** Grep for other imports of `PRODUCT_TYPE_MAPPING` / `CODEX_PRODUCT_TYPES` from `sync_service` and repoint them.
- [ ] **Step 4: Run the whole suite** — `python -m pytest -q`. Expected: the 7 known pre-existing failures only.
- [ ] **Step 5: Commit** — `fix(sync): product_type passes the Codex enum through; old mapping removed`.

---

### Task 9: Apply results to Grimoire

**Files:**
- Create: `backend/grimoire/services/classification/apply.py`
- Modify: `backend/scripts/classify.py` (add `apply --run NAME`)
- Test: `backend/tests/services/classification/test_apply.py`

**Interfaces:**
- Produces `effective_levels(min_: int | None, max_: int | None) -> tuple[int | None, int | None]` (both present and `min <= max` → as given; otherwise `(None, None)`).
- Produces `@dataclass ApplyReport(applied: int, skipped_applied: int, skipped_error: int, skipped_no_product: int)` and `async apply_run(db, run_name: str) -> ApplyReport`. Per result with `product_id`, no `error`, `applied_at is None`: `product.product_type = product_type_new`; levels from `effective_levels(level_min_new, level_max_new)` written only when both are not `None`, otherwise untouched; `applied_at = now(UTC)`. Commits once at the end. Sibling rows are never touched.

- [ ] **Step 1: Write the failing tests**

```python
async def test_apply_overwrites_type_and_replaces_levels(db): ...        # "Supplement"/(3,5) → "adventure"/(1,3)
async def test_apply_writes_level_zero(db): ...                            # new (0,0) → product levels (0,0)
async def test_apply_null_levels_keep_existing(db): ...                   # new (None,None), existing (3,5) stays
async def test_half_range_and_inverted_range_are_no_range():
    assert effective_levels(3, None) == (None, None) and effective_levels(5, 3) == (None, None) and effective_levels(0, 2) == (0, 2)
async def test_apply_skips_errors_and_is_idempotent(db): ...              # error row untouched; second apply_run → applied == 0, product unchanged
async def test_apply_leaves_sibling_untouched(db): ...                    # two products in same folder; only the matched id changes
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement `apply.py` and the `apply` subcommand** (prints the report).
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Commit** — `feat(classification): apply a run's results to Grimoire products`.

---

### Task 10: Export to Codex (dry run, report, reviewed live send)

**Files:**
- Create: `backend/grimoire/services/classification/export.py`
- Modify: `backend/scripts/classify.py` (add `export [--run NAME] [--min-confidence F] [--out path]` and `export --live --from reviewed.csv --yes`)
- Test: `backend/tests/services/classification/test_export.py` (httpx mocked with `httpx.MockTransport`)

**Interfaces:**
- Produces `@dataclass ExportItem(codex_id: str, slug: str, title: str, fields: dict[str, int | str], kinds: dict[str, str], confidence: float | None, type_evidence: str | None, level_evidence: str | None)`.
- Produces `async build_items(db, run_name: str, min_confidence: float = 0.0) -> list[ExportItem]`: per result without `error` and with `codex_product_id`: `product_type` included when `product_type_new != codex.product_type` and not (`product_type_new == "other"` and `codex.product_type not in (None, "", "other")`); each level included when `effective_levels` gives a value that differs from Codex's. Items with no fields are dropped. `kinds[field]` is `"fill"` when the Codex value is `None`, `""` or `"other"`, else `"correction"`. Never contains `core_rules` or a `None` value.
- Produces `async codex_token(db) -> str` (settings `codex_api_key` via `json.loads`, else `settings.codex_api_key`).
- Produces `send_items(items: list[ExportItem], token: str, dry_run: bool, client: httpx.Client | None = None) -> dict[str, dict]` (keyed by codex id → that item's result object from Codex); chunks of 100; headers `Authorization: Token …`, `User-Agent: Grimoire/classification`; raises on non-2xx.
- Produces `write_report(items, outcomes, out: Path) -> None`: columns `send, codex_id, slug, title, type_old, type_new, type_kind, min_old, min_new, max_old, max_new, level_kind, confidence, type_evidence, level_evidence, codex_status, protected, errors`; `send` is `yes`. Prints a summary: counts by kind, by status, top type transitions, and how many rows have `confidence < 0.6`.
- Produces `read_reviewed(path: Path) -> list[ExportItem]` (rows where `send` is `yes`, case-insensitive; rebuilds `fields` from the `*_new` columns, skipping blanks).
- Live mode also stamps `exported_status` and `exported_at` on the matching `ClassificationResult` rows.

- [ ] **Step 1: Write the failing tests**

```python
async def test_build_items_only_differences_and_fill_vs_correction(db): ...     # other→adventure is fill; adventure→tools is correction; equal type omitted
async def test_other_is_fill_only(db): ...                                       # new "other" over Codex "adventure" → no product_type field; over Codex "other" → omitted (equal); over None → fill
async def test_items_never_carry_none_or_core_rules(db): ...
async def test_min_confidence_filters(db): ...
def test_send_items_chunks_of_100_and_headers(): ...                             # 250 items → 3 POSTs via MockTransport; dry_run True in body; User-Agent set
def test_send_items_not_found_lands_in_outcomes(): ...                           # Codex returns status not_found → outcomes[id]["status"] == "not_found", no raise
def test_report_roundtrip_respects_send_column(tmp_path): ...                   # write 3 rows, flip one to "no", read_reviewed → 2 items with the right fields
def test_cli_live_requires_from_and_yes(): ...                                   # argparse: --live without --yes → SystemExit
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement `export.py` and the subcommand.** Dry run re-dumps and re-imports the snapshot first (Task 2 functions) unless `--no-refresh`.
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Commit** — `feat(classification): dry-run export, review CSV and gated live send to Codex`.

---

### Task 11: Vocabulary migration for the rest of the library (Phase D)

**Files:**
- Modify: `backend/grimoire/services/classification/apply.py` (add `apply_vocab_migration`)
- Modify: `backend/scripts/classify.py` (add `vocab-migrate [--dry-run]`)
- Test: `backend/tests/services/classification/test_apply.py` (extend)

**Interfaces:**
- Produces `async apply_vocab_migration(db, dry_run: bool = False) -> dict[str, int]` (counts by target enum value plus `"unmapped"`). Creates or reuses a run named `vocab-migration` (`model="table"`, `effort="none"`). For every product whose `product_type` is not already an enum value and has no applied `ClassificationResult`: `normalize_free_text` → if a value, write a `ClassificationResult(source="vocab", product_type_old, product_type_new, applied_at=now)` and set the product's type; if `None`, count as unmapped and leave it.

- [ ] **Step 1: Write the failing tests**

```python
async def test_vocab_migration_maps_table_values_and_records_old(db): ...   # "Supplement" → "supplement" with a result row holding old value
async def test_vocab_migration_leaves_unmapped_and_ai_applied_rows(db): ... # "Anthology" stays; a product with an applied pdf result is not touched
async def test_vocab_migration_dry_run_writes_nothing(db): ...
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Commit** — `feat(classification): deterministic vocabulary migration for non-Codex products`.

---

### Task 12: Identification path uses the enum and keeps level 0 (Phase C)

**Files:**
- Modify: `backend/grimoire/processors/ai_identifier.py:169-190,335,523`
- Modify: `backend/grimoire/api/routes/ai.py:67-70,251-254`
- Test: `backend/tests/processors/test_identification_prompt.py` (new), `backend/tests/api/test_ai_levels.py` (new)

**Interfaces:**
- `IDENTIFICATION_PROMPT` lists the 14 enum values for `product_type` ("one of: adventure, …, other") and carries the level rules sentence from `SYSTEM_PROMPT` (never infer, 0 is real). `_format_prompt` is unchanged.
- The two `text[:4000]` sites call `build_excerpt({"markdown": text}, header={"filename": filename or ""}).text` so the model sees the head plus level windows.
- `ai.py` writes `level_range_min`/`level_range_max` when the value `is not None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_identification_prompt_uses_enum_not_examples():
    assert "one of:" in IDENTIFICATION_PROMPT and "core_rulebook" in IDENTIFICATION_PROMPT
    assert 'e.g. "Adventure"' not in IDENTIFICATION_PROMPT

async def test_identify_apply_stores_level_zero(client, db): ...   # POST the apply-identification route with level_range_min 0 → product.level_range_min == 0
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite.** Expected: known pre-existing failures only.
- [ ] **Step 5: Commit** — `fix(identify): enum product types, excerpt instead of text[:4000], level 0 survives`.

---

### Task 13: Frontend labels for the enum

**Files:**
- Create: `frontend/src/lib/productType.ts`
- Modify: `frontend/src/components/ProductCard.tsx:142-145,303-306`, `frontend/src/components/ProductDetail.tsx:842-843,1080-1085`, `frontend/src/components/FilterDrawer.tsx:437`, `frontend/src/pages/Library.tsx:487`

**Interfaces:**
- Produces `PRODUCT_TYPES: readonly string[]` (the 14), `PRODUCT_TYPE_LABELS: Record<string, string>` (`core_rulebook` → "Core Rulebook", `gm_tools` → "GM Tools", `character_options` → "Character Options", others title-cased), `productTypeLabel(value: string | null | undefined): string` (label when known, else the value as-is, else `""`).
- Display sites render `productTypeLabel(product.product_type)`. The ProductDetail edit field becomes a `<select>` over `PRODUCT_TYPES` with labels plus an empty option; filter chips show the label but filter on the raw value.

- [ ] **Step 1: Create `productType.ts` and wire the five sites.**
- [ ] **Step 2: Gate** — from `frontend/`: `npx tsc -b`. Expected: no errors.
- [ ] **Step 3: Manual check** in the running app: a card for an applied product shows "Core Rulebook", the filter chip shows the label, the edit dropdown lists 14 entries.
- [ ] **Step 4: Commit** — `feat(ui): labels and a select for the Codex product_type enum`.

---

## Run sequence (Michael, with the CLI)

All from `backend/`, miniconda interpreter.

1. `python scripts/classify.py dump-codex && python scripts/classify.py import-codex data/classification/codex_snapshot.csv`
2. `python scripts/classify.py match` — read the fuzzy sample; re-run with `--fuzzy-threshold 95` if any is wrong.
3. `python scripts/classify.py select-pilot`
4. `python scripts/classify.py submit --run pilot-sonnet --model claude-sonnet-5-5 --pilot` and `submit --run pilot-opus --model claude-opus-5-5 --pilot`
5. `python scripts/classify.py collect --run pilot-sonnet --wait` and the same for `pilot-opus`
6. `python scripts/classify.py pilot-sheet --runs pilot-sonnet,pilot-opus --out data/classification/pilot.csv` — Michael fills `true_type`, `true_min`, `true_max`.
7. `python scripts/classify.py pilot-score --runs pilot-sonnet,pilot-opus --truth data/classification/pilot.csv` — choose the model; the printed cost per product × 7,327 is the full-run projection.
8. `python scripts/classify.py submit --run full --model <chosen> --all` then `collect --run full --wait`
9. `python scripts/classify.py apply --run full`
10. `python scripts/classify.py vocab-migrate --dry-run`, then without `--dry-run`.
11. `python scripts/classify.py export --run full --out data/classification/export-report.csv` — dry run against Codex; review, flip `send` to `no` where needed.
12. `python scripts/classify.py export --live --from data/classification/export-report.csv --yes`

Do not press "Sync all" in Grimoire's Settings until the Codex contract realignment lands (spec, Phase C hazard).

## Self-review notes

- Spec §1–§8, Phase C, Phase D each map to a task (2, 3, 4, 5, 6, 7, 10, 8+12+13, 11). Costs are printed by `submit` and `pilot-score`.
- Names reused across tasks: `build_excerpt`/`Excerpt` (4 → 6, 12), `parse_output`/`build_request` (5 → 6), `effective_levels` (9 → 10), `normalize_free_text` (1 → 8, 11), `import_snapshot`/`dump_codex` (2 → 10).
- Server-side refusal fallback is deliberately not used on the batch path; a refusal is an error row and is re-sent by hand if it ever happens.
