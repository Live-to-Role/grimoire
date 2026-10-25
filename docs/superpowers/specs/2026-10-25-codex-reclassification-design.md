# Codex reclassification: product type and level range

**Date:** 2026-10-25
**Status:** Open questions answered 2026-10-25, awaiting approval

## Intent

Codex (codex.livetorole.com) needs system × type × level hub pages for AI
search. On prod (2026-10-24), 3,797 of 7,327 products are `product_type`
`other`, 68 have a level range, and some `adventure` rows are wrong (a d30
height table, an NPC generator, spell cards). Grimoire holds the PDFs for
about 90% of those products, so Grimoire reads the books, decides, and
sends the answers to Codex through the owner-authorised override endpoint.

## What we learned before designing (the premise was wrong)

The work-machine prompt assumed Codex was seeded from Grimoire and that
Grimoire's 4,000-character identification prompt caused the `other` rows.
The Codex database says otherwise:

- Codex's products were bulk-imported in 2026-08 from the owner's
  DriveThruRPG purchase library: 7,164 of 7,327 carry a `dtrpg_id`, **zero**
  have a `catalog_filehash` row, and only 2 contributions have source
  `grimoire`. The `other` values are the DTRPG importer's "shrug"
  (`merge_rules.py`), not Grimoire's output.
- Grimoire never contributed these products, which is why its 3,393 level
  ranges never reached Codex.
- There is therefore no hash join. The join is the **folder name**: Grimoire
  files live at `D:\Drivethrurpg\<Publisher>\<DTRPG title>\<file>.pdf`, and
  the DTRPG title folder matches the Codex title.

Grimoire's own weaknesses are real and get fixed in passing (see Phase C),
but they are not the cause of Codex's data problem.

## Goals

1. Every Codex product gets a `product_type` from Codex's 14-value enum and
   a level range when, and only when, the book states one.
2. Every decision is auditable: old value, new value, confidence, and the
   text span it rests on, stored per product in Grimoire.
3. Nothing reaches Codex until Michael has read a dry-run report and
   approved it.
4. Accuracy is measured on a 150-product pilot that Michael hand-labels,
   on both candidate models, before the full run.
5. Grimoire's `product_type` column adopts the Codex enum so there is one
   vocabulary and the sync needs no mapping.

## Non-goals

- Classifying the ~11,000 Grimoire products that are not on Codex with the
  AI. (A later run can reuse everything built here.)
- A web UI for any of this. It is a CLI Michael runs on the home machine.
- Changing anything else on a product: title, system, genre, tags,
  description.
- Changes to Codex. Its override endpoint exists and is merged.

## Anti-goals (failure even if it "works")

- Sending any write to Codex without explicit approval of the report.
- Inferring a level from "beginner", "introductory", "low-level",
  "epic", page count, or system defaults. Unstated means null.
- Emitting `core_rules`.
- Treating a page number, spell level, monster level, dungeon level, or
  "tier" as a character level.
- Silently losing level 0. DCC funnels are level 0 and must survive every
  layer (prompt, parsing, storage, export).

## Constraints

- Budget: $250 in API credits total, pilot included.
- Message Batches API (half price). No real-time calls for the bulk run.
- Input per product is an excerpt of about 4k tokens, never the whole book.
- Codex's endpoint: `POST /api/v1/classification/`, `Authorization: Token`,
  at most 100 items per request, `dry_run` defaults true, levels 0–40,
  `core_rules` refused, null means "leave alone". See codex
  `docs/GRIMOIRE_CLASSIFICATION_OVERRIDE.md`.
- Excerpts of publishers' books go to the Anthropic API. Michael approved
  this (API data is not used for training by default).
- Grimoire is local, single-user. No production hardening.

## Decisions already taken

| Decision | Choice | By |
|---|---|---|
| Scope of the AI run | Codex's 7,327 products only | Michael |
| Grimoire `product_type` | Overwritten with the Codex enum | Michael |
| Join key | Publisher folder + DTRPG title folder, then fallbacks | Claude, from the data |
| Pilot labels | A CSV Michael fills in | Claude (default) |
| Pilot models | Sonnet 5.5 and Opus 5.5, both over the same 150 | Claude (default) |
| Where the code lives | `backend/grimoire/services/classification/` + CLI `backend/scripts/classify.py` | Claude |
| Products with no PDF in Grimoire | Classified from the Codex title + description, flagged as such | Claude |

## The pieces

### 1. Codex snapshot

A new table `codex_products` holds the dump pulled from the Codex
database (id, slug, title, publisher, product_type, level_range_min,
level_range_max, dtrpg_id, page_count, description text) plus the match
result: `grimoire_product_id`, `match_method`
(`folder` | `title` | `fuzzy` | `manual` | `none`), `match_score`.

The dump is taken with `psql` against Railway's `DATABASE_PUBLIC_URL`
(the `railway` link lives in the grimoire directory). A fresh dump is
taken immediately before the final export so the diff is against current
Codex values.

### 2. Matching

Order, first hit wins:

1. Normalised (publisher, title) equals Grimoire's (publisher folder,
   product folder). Measured: 6,502.
2. Normalised title equals a product folder. Measured: 74.
3. Fuzzy: token-set similarity of the Codex title against product folders
   and file stems, same publisher when Codex has one, threshold the
   builder tunes on the known matches so it produces no false positive on
   them. Many of the 751 unmatched have filename-style titles like
   `1008573-BeachEncounters`.
4. Manual: a CSV of unmatched products Michael can fill in if he wants.
   Not required.

When a folder holds several PDFs (1,924 cases), pick one: skip
`is_duplicate`, `is_missing`, `text_unextractable`, then take the largest
`page_count`, then the largest file. The chosen file's id is the match.

Normalisation: lowercase, strip everything but letters and digits to
single spaces. The builder should check a sample of fuzzy matches by eye
before trusting the threshold.

### 3. Excerpt builder

From `data/text/<id>.json` (`pages` is a per-page list):

- **Head:** pages from the start until about 2,500 tokens. This covers
  cover, credits, table of contents, and usually the introduction where
  levels are stated.
- Older extractions (about 13% of files) have only `markdown` and no
  `pages` list. The builder falls back to the unpaged text, tags windows
  with a character offset instead of a page, and flags the excerpt.
- **Level windows:** up to 6 windows of about 150 tokens centred on
  matches of level patterns anywhere in the book, each tagged with its
  page number, overlapping windows merged, earliest first. Patterns
  include: `level(s) N`, `N-N`, `N to N`, `Nth level`, `Nth-level`,
  `0-level`, `level 0`, `funnel`, `character levels`, `characters of
  level`, `tier N`. The builder will refine these on the pilot.
- **Header:** filename, publisher folder, product folder, page count,
  Codex title, Grimoire's current type and levels. The header is data for
  the model, not instruction.
- Hard cap about 4,000 tokens. The head is trimmed before the windows are.

Products with no Grimoire match get an excerpt made of the Codex title,
publisher, and description, and the result is flagged `source =
description`. A reviewer can treat those with less trust.

### 4. Prompt and output

One system prompt (cached, identical across requests) that:

- Defines each of the 14 enum values in one or two lines, with the
  boundaries that matter: adventure vs supplement, sourcebook vs setting,
  supplement vs character_options, tools vs gm_tools, map vs supplement,
  magazine vs zine, core_rulebook vs quickstart (a quickstart is
  `core_rulebook`). `core_rules` does not appear.
- States the level rules from the anti-goals, with the DCC level-0 case
  spelled out, and that a range "for levels 3-5" is min 3 max 5, a single
  "for 1st level characters" is min 1 max 1.
- Asks for a confidence from 0 to 1 and for the exact text span the type
  and the level rest on.

Output is structured: `output_config.format` with a JSON schema, not free
text. Fields: `product_type` (enum), `level_range_min` and
`level_range_max` (integer 0–40 or null), `confidence` (number),
`type_evidence` (string), `level_evidence` (string or null),
`notes` (short string). Model: the pilot decides between
`claude-sonnet-5-5` and `claude-opus-5-5`. Effort starts at `medium`;
the builder may try `low` on the pilot since classification often holds
there. Server-side refusal fallback is on. A `refusal` or `max_tokens`
stop is recorded as an error for that product, not a value.

### 5. Runs and results

Two new tables:

- `classification_runs`: id, name, model, effort, batch_id, status,
  request_count, submitted_at, completed_at, input_tokens, output_tokens,
  cost_usd.
- `classification_results`: id, run_id, product_id (Grimoire, nullable
  for description-only), codex_product_id, source (`pdf` | `description`),
  old and new `product_type`, old and new `level_range_min` and
  `level_range_max`, `confidence`, `type_evidence`, `level_evidence`,
  `notes`, `raw_response`, `error`, `applied_at`, `created_at`.

A run never applies anything. `apply` is a separate step that writes the
new values onto Grimoire's `products` row and stamps `applied_at`.

Apply rules (Claude's call, revertable because the old values are kept):

- `product_type`: the result replaces whatever Grimoire held, including
  `other` replacing free text. That is the overwrite decision.
- Levels: a non-null result replaces an existing Grimoire level; a null
  result leaves the existing level alone. Grimoire has no record of which
  levels a person set, and the existing ones came from the same weak
  identification, so the evidence-backed answer wins. Written with
  `is not None`, never truthiness. A half range (min without max or the
  reverse) is treated as no range.
- Only the matched file's row is written. Sibling PDFs in the same folder
  (1,924 folders) are left alone: they are not separate Codex rows, and a
  bundle folder can hold different books.

### 6. Pilot

- `select-pilot` picks 150 Codex products: stratified by current Codex
  type with a floor of 5 per type, `other` and `adventure` weighted up
  since that is where the errors are, 15 of the 150 drawn from the
  description-only set, and the known-wrong examples always included:
  Frugal GM's d30 Height & Weight tables, d30 NPC Background Generator,
  d30 Quick NPC Personality Generator, and Generic Spell Effect Cards,
  all currently `adventure` on Codex (Frugal GM has 22 `d30 ...` rows
  filed that way). The selection is saved so both models see the same
  150.
- `submit --run pilot-sonnet --model claude-sonnet-5-5` and the same for
  Opus. Two batches, same requests.
- `pilot-sheet` writes a CSV for Michael: id, title, publisher, a path to
  the excerpt file, current Codex type and levels, then for each model its
  type, levels, confidence, evidence, and blank columns `true_type`,
  `true_min`, `true_max`. Michael fills in the truth.
- `pilot-score --truth <csv>` reports per model: type accuracy, level
  exact-match accuracy, level false-positive rate (a level given where
  truth is null), and measured cost per product. The full-run cost is
  projected from the measured tokens.

Michael chooses the model from that report. Nothing in the pilot is
applied or exported.

### 7. Full run

`submit --run full --model <chosen>` over every matched and
description-only Codex product, in batches of up to 10,000 requests.
`collect` polls and stores results. `apply` writes Grimoire. Then the
export.

### 8. Export

`export --dry-run` (the default):

1. Re-dump Codex and refresh `codex_products`.
2. For each Codex product with a result, build an item with only the
   fields that differ from Codex's current value. Null never travels.
   `other` is fill-only: it never replaces a specific Codex type. A model
   that cannot place a book does not get to downgrade one a person or the
   importer placed; the row shows up in the report's low-confidence tail
   instead.
3. POST in chunks of 100 with `dry_run: true`, capturing each item's
   status (`changed`, `unchanged`, `protected`, `not_found`, `invalid`).
4. Write a report CSV: codex id, slug, title, for each field old → new,
   kind (`fill` when the old value is `other` or null, `correction`
   otherwise), confidence, evidence, Codex's dry-run status and any
   protected fields, and a `send` column defaulting to `yes`. Plus a
   summary: counts by kind, by type transition, by status, and the
   low-confidence tail.

Michael reviews the CSV and flips `send` to `no` on any row he vetoes.
`export --live --from <reviewed csv>` sends only rows marked `yes`, with
`dry_run: false`, and is refused unless `--yes` is also passed.
`--min-confidence N` on either mode drops rows below N before anything
else. The live run records the Codex response per item so a re-run
reports `unchanged` rather than re-sending.

**Prerequisite, verified 2026-10-25:** the endpoint is deployed on prod
(a dry run answered 401, not 404) and `may_overwrite_classification` is
ticked, but the token Grimoire holds in its settings table is rejected
("Invalid token"). The current Grimoire token from Codex's admin must be
saved in Grimoire settings before the dry run. The request also needs a
real `User-Agent`; Cloudflare returns 403 error 1010 to Python's default.

## Phase C: stop the data rotting again

Ordering matters for the first item; the rest can follow the run.

- **Before `apply`:** `sync_service.PRODUCT_TYPE_MAPPING` and
  `CODEX_PRODUCT_TYPES` go. Today they would turn the new enum values
  back into the old ones (`core_rulebook` → `core_rules`, which Codex
  refuses; `setting` → `sourcebook`; `map` → `other`). The column holds
  the enum, so `normalize_product_type` passes a valid enum value through
  and maps nothing else. `codex_eligibility.IMAGE_PRODUCT_TYPES` and the
  type check in `library.py` learn the enum values too.
- `IDENTIFICATION_PROMPT` asks for the enum and uses the excerpt builder
  instead of `text[:4000]`.
- `ai.py` stores levels with `is not None` (level 0 currently vanishes).
- The frontend shows a label for each enum value (`core_rulebook` →
  "Core Rulebook") wherever `product_type` is displayed or filtered.

**Known hazard, not fixed here:** `codex_contribute_enabled` is on in the
live settings, and the ordinary sync treats any product whose hash Codex
does not know as a new product. Codex knows none of these hashes, so a
"Sync all" would try to create duplicates of the 6,500 matched products.
The fix belongs to the Codex contract realignment work, which already
records this bug. Until it lands: do not run a bulk sync.

## Phase D: fold the rest of the library into the enum

Michael chose to map the common free-text values deterministically so the
Library filter does not show two vocabularies. No AI. Runs as a
classification run named `vocab-migration` so every old value is kept in
`classification_results` and the step is revertable. Applied only to
products that have no AI result; values not in the table are left as
they are. The table (Claude's draft, rows with 5 or more products):

| Enum | Grimoire values |
|---|---|
| `adventure` | Adventure, adventure, Campaign |
| `supplement` | Supplement, Expansion, Accessory |
| `sourcebook` | Sourcebook |
| `setting` | Setting, Campaign Setting |
| `core_rulebook` | Core Rulebook, Rulebook, Rules, Quickstart, Quick Start, Quickstart Guide, Quick Start Guide, Quick-Start Rules, Quick Start Rules, Jumpstart, Starter Set, RPG, Roleplaying Game, Game |
| `bestiary` | Bestiary, Monster |
| `character_options` | Character Options, Class, Class/Archetype, Background, Player's Guide |
| `gm_tools` | GM Tools, GM's Resource, Generator |
| `tools` | Character Sheet, Character Sheets, Token, Portrait, Handout, Item Cards, Cards, Spell Sheet, Pregenerated Character, Pregenerated Characters, Template, Paper Model, Quick Reference, Reference |
| `map` | Map, Maps, Art/Maps, Dungeon Backdrop |
| `magazine` | Magazine |
| `zine` | Zine |
| `screen` | GM Screen |
| `other` | Stock Art, Texture, Comic, Comic/Graphic Novel, Graphic Novel, Fiction, Short Story |

Left alone on purpose: `Anthology` (adventure or fiction), `Character`
(sheet or option), and everything under 5 products.

## Costs (estimates, re-measured on the pilot)

First-party batch prices: Opus 5.5 $2 in / $10 out per MTok, Sonnet 5.5
$1 in / $5 out per MTok. About 7,300 requests at ~4.5k input tokens and
~500 output tokens including thinking:

| Model | Input | Output | Estimate |
|---|---|---|---|
| Opus 5.5 | ~$66 | ~$37 | ~$100 |
| Sonnet 5.5 | ~$33 | ~$18 | ~$50 |
| Pilot, both models | | | ~$3 |

Both fit the $250 budget with room for a partial re-run. The pilot's
measured token counts replace this table before the full run.

## Acceptance criteria

- [ ] `codex_products` holds 7,327 rows; match report shows method counts
      and a reviewed sample of fuzzy matches.
- [ ] Excerpt builder has tests for: head trimming, level-window merging,
      page tagging, the 4k cap, a DCC "0-level" sample, and a page-number
      sample that must not match.
- [ ] Pilot sheet produced for 150 products on both models; score report
      produced from Michael's truth file.
- [ ] Full run stored with per-product old, new, confidence, evidence.
- [ ] `apply` writes level 0 correctly (test).
- [ ] Dry-run report produced; every item's Codex status captured; no
      `core_rules` and no nulls in any payload (test).
- [ ] `export --live` refuses without `--yes` (test).
- [ ] Phase C: identify prompt uses the enum; sync mapping removed; tests
      updated; frontend labels in place.
- [ ] Phase D: vocab migration applied as a revertable run; filter shows
      one vocabulary plus the deliberately unmapped stragglers.

## Left to the builder

- Exact regexes and window sizes; tune on the pilot.
- Fuzzy threshold and which similarity function.
- Prompt wording for the enum boundaries (seed it from Codex's own
  `ProductType` help text if any).
- Whether `anthropic` is added as a dependency (recommended) or the
  existing `httpx` client is extended. The SDK's batch helpers argue for
  the dependency.
- Batch size and polling cadence.
- CSV layout details.

## Answers from Michael (2026-10-25)

- Veto: the report CSV carries a `send` column; the live export reads the
  reviewed CSV; `--min-confidence` drops the tail. (Folded into §8.)
- Map the common free-text types deterministically. (Phase D.)
- Known-wrong examples: found in the Codex dump by Claude. (Folded into §6.)
- `may_overwrite_classification` is ticked and the endpoint is deployed.
  Grimoire's stored token is stale; see the prerequisite in §8.
