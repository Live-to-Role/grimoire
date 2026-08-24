# Multi-Format Scanning — Design

Status: draft for review
Date: 2026-08-23
Depends on: `2026-08-23-codex-contract-realignment.md` (phases 0–2 land
first; its Phase 3 eligibility predicate is *completed* here, in Phase 2 —
see [Codex eligibility](#codex-eligibility))

## What

Teach Grimoire to scan, catalogue and process non-PDF documents. First cut:
**EPUB, DOCX and ODT**. Later phases add the flat-text family (TXT, MD, RTF)
and comic archives (CBZ) on the same machinery.

## Why

A tabletop library is not all PDFs. Itch.io bundles ship EPUB, homebrew and
third-party supplements circulate as DOCX/ODT, and the "PDFs only" scan means
those files are invisible to search, collections, campaigns and the bestiary.
The user request was "also scanning txt, rtf, docx, etc." — the underlying ask
is that the library catalogue the documents a user actually owns, not one
container format.

## Design principles

- **The PDF path does not change.** All existing PDF behaviour — pdfplumber /
  pymupdf4llm / marker routing, OCR fallback, image-content classification —
  moves behind a handler unchanged, and is the reference implementation.
- **Reuse the two existing seams.** The pipeline already narrows to two
  contracts, and every new format targets those rather than growing new ones.
- **Formats are opt-in.** An existing user's next scan must not change
  behaviour until they enable a format.

---

## Architecture: a format handler registry

Two seams already exist in the codebase, which is why this is a refactor
rather than a rewrite:

**Seam 1 — the extraction JSON.** `process_text_extraction_sync`
(`services/processor.py:163`) writes `data/text/{product_id}.json` and
everything downstream (FTS, embeddings, monster extraction, AI identify)
reads it back through `get_extracted_text` / `get_extracted_pages`. The
contract is:

```python
{
  "markdown": str,
  "pages": [{"page": int, "markdown": str}, ...],
  "total_pages": int,
  "method": str,          # "pymupdf4llm" | "epub" | "docx" | ...
  "char_count": int,
}
```

Any handler that produces this dict inherits search, semantic search,
statblock extraction and AI identification for free.

**Seam 2 — cover + metadata.** `extract_cover_image(path, out_path, size) -> bool`
(`services/processor.py:44`) and `extract_all_metadata(path) -> ExtractedMetadata`
(`services/metadata_extractor.py:410`). Both are pure functions over a path.

### The protocol

New module `grimoire/formats/`:

```python
# grimoire/formats/base.py
class FormatHandler(Protocol):
    extensions: tuple[str, ...]        # (".epub",)
    name: str                          # "epub"
    paginated: bool                    # False for flow formats

    def extract_text(self, path: Path, **opts) -> dict: ...        # seam 1
    def extract_metadata(self, path: Path) -> ExtractedMetadata: ...
    def extract_cover(self, path: Path, out: Path, size: int) -> bool: ...
    def page_count(self, path: Path) -> int | None: ...
    def needs_ocr(self, path: Path) -> bool: ...                   # False for all but PDF
```

- `grimoire/formats/registry.py` — `get_handler(path) -> FormatHandler | None`,
  `enabled_extensions(db) -> set[str]`, registration by extension.
- `grimoire/formats/pdf.py` — wraps the existing functions verbatim. No new logic.
- `grimoire/formats/epub.py`, `docx.py`, `odt.py`.

Call sites that change from direct-call to `get_handler(path).…`:

| Call site | Currently |
|---|---|
| `services/processor.py:44` `extract_cover_image` | `fitz.open` |
| `services/processor.py:82` `extract_pdf_metadata` | `fitz.open` |
| `services/processor.py:163` `process_text_extraction_sync` | `extract_text_to_markdown` |
| `services/metadata_extractor.py:159,222` | `fitz.open` |
| `services/queue_processor.py:295` `_diagnose_pdf_unextractable` | `fitz.open` |
| `services/queue_processor.py:312` `handle_text_task` (OCR + image-content routing) | PDF-only branches, guard with `handler.needs_ocr` |

---

## Data model

New column on `products`:

```python
file_type: Mapped[str] = mapped_column(String(10), nullable=False, default="pdf")
# Index("ix_products_file_type", "file_type")
```

Migration in `grimoire/migrations/` (matching the existing
`add_*_columns.py` pattern) backfilling every existing row to `"pdf"`.

**Naming trap:** `Product.format` already exists and means *publication*
format (`pdf` / `print` / `both`). Do not reuse or repurpose it. New column is
`file_type`.

Docstrings across `models/product.py` ("A PDF product in the library"),
`scanner.py` and the API schemas need generalising to "document".

### Synthetic pagination

Flow formats have no pages, but `page_count`, per-page embeddings, monster page
references, the `_oversized_skip_reason` page guard and citation display all
assume them. Handlers for flow formats chunk extracted text into pseudo-pages
of ~3000 characters, **splitting on the nearest heading or paragraph boundary**,
and emit them in the same `pages` list.

- EPUB paginates per **spine item** (chapter) first, then splits any chapter
  over the chunk ceiling. Chapter boundaries are real structure — better than
  a blind character count.
- DOCX/ODT paginate on heading-1/2 boundaries, then by character ceiling.
- The extraction JSON gains `"pagination": "synthetic" | "native"`.
- API surfaces it so the UI can say "section 4" instead of "page 4"; the
  bestiary's page citations use the same field.

---

## Per-format handlers

| Format | Text | Metadata | Cover | Dep |
|---|---|---|---|---|
| EPUB | spine items → HTML → markdown | OPF: title, author, publisher, date, language, description | **embedded cover image** (OPF `cover` meta / `cover-image` property) | `ebooklib`, `beautifulsoup4` |
| DOCX | paragraphs + tables → markdown, heading levels preserved | core properties: title, author, created, subject, keywords | none → placeholder | `python-docx` |
| ODT | text:p / text:h + tables → markdown | `meta.xml`: title, creator, date, subject, keyword | none → placeholder | `odfpy` |

All three are small pure-Python packages. No native toolchain, no
LibreOffice shell-out, nothing in the weight class of the existing torch
dependency.

Notes:
- EPUB metadata is genuinely rich and should feed `apply_metadata_to_product`
  with **higher confidence than filename parsing** — an EPUB's declared
  publisher beats a guess from `"Publisher - Title.epub"`.
- DOCX tables map onto the existing table markdown conventions the
  table_reconstructor already emits, so statblock extraction keeps working.
- `needs_ocr` is `False` for all three; the `ocr_text` and `extract_images`
  queue branches in `handle_text_task` must be reached only when
  `handler.needs_ocr(path)` is true, otherwise a text-light EPUB gets routed
  into an OCR path that cannot open it.
- Encrypted/DRM EPUB is the analogue of an encrypted PDF: set
  `text_unextractable` with reason `"drm-protected"` through the existing
  disposition machinery rather than retrying forever.

## Covers: generated placeholder cards

Order of preference per document:

1. **Embedded cover** — EPUB almost always has one; use it, resized through
   the existing thumbnail path.
2. **Generated placeholder card** — a PIL-rendered 300px card: title text
   wrapped over a background tinted deterministically from a hash of the
   title, with a format badge ("DOCX", "ODT") in the corner.

The card writes to `settings.covers_dir / f"{product.id}.jpg"` exactly like a
PDF cover, so `cover_extracted`, `cover_image_path`,
`generate_thumbnail_for_product`, the grid, the gallery and the API routes all
stay untouched. Frontend needs no cover-specific work.

New module `grimoire/formats/placeholder.py`. Font: bundle one, or fall back
to PIL's default rather than depending on a system font being present —
the native Windows install cannot assume DejaVu.

## Opt-in per format

New setting key `enabled_file_types`, JSON array, read in `get_scan_settings`
(`scanner.py:194`) alongside the existing scan settings. Settings page gets a
checkbox group listing every registered handler.

**Every format other than PDF is off by default — permanently, not just during
rollout.** The default is `["pdf"]` on both fresh installs and upgrades, and a
new handler added in a later phase never enables itself. A user who has never
opened Settings scans exactly what they scan today, in this release and every
release after it.

**Why this matters:** DriveThruRPG and itch bundles are full of `readme.txt`,
`license.txt`, `installation notes.docx` and `changelog.rtf`. Enabling a
format without protection turns each of those into a Product with a
placeholder cover. Alongside the toggles, add to `DEFAULT_EXCLUSION_RULES`
(`models/exclusion.py:50`):

```python
{"rule_type": "filename", "pattern": "readme*",    ...},
{"rule_type": "filename", "pattern": "license*",   ...},
{"rule_type": "filename", "pattern": "licence*",   ...},
{"rule_type": "filename", "pattern": "changelog*", ...},
{"rule_type": "filename", "pattern": "credits*",   ...},
```

New rules must be added idempotently to **existing** installs — a fresh
`config/install`-style default is not enough when the table is already
populated.

⚠️ **There is no precedent to copy here.** An earlier draft said to match how
`LEGACY_SIZE_MIN_PATTERN` is migrated in `exclusion_service.py:135`. No such
symbol exists anywhere in the repo, and the seeding function —
`seed_default_rules`, at `exclusion_service.py:154` — opens with a blanket
`if existing: return 0` over every `is_default` rule. So it has never added a
rule to a populated table and there is no per-rule idempotency to follow. This
is a migration to write from scratch, in `grimoire/migrations/` alongside the
`add_*_columns.py` files: insert each new default only when no rule with that
`rule_type` + `pattern` already exists, and leave a user's disabled or edited
rules alone.

⚠️ **The `size_min` floor has already been lowered — the gap is existing
installs.** Two earlier drafts of this section were both wrong, in opposite
directions, and the second was wrong for an instructive reason: it was written
against `60d6e94`, two commits behind main, where `models/exclusion.py:69` did
read `10240`. `834d4e8` ("stop skipping one-page PDFs") landed about ninety
minutes before that draft and lowered the shipped default to **1024**
(`models/exclusion.py:72`, with `tests/services/test_size_min_default_correction.py`
covering it). So the lowering is done and is not this plan's work.

What is still open is the half the blanket `if existing: return 0` above
guarantees: **a database seeded before `834d4e8` still holds a 10240 rule**,
and nothing will ever update it. The code default and the deployed default
disagree on every pre-existing install, including Michael's. That is the same
stranding problem as the new filename rules, it wants the same idempotent
migration, and it is a better argument for writing that migration than the one
this section used to make.

It also removes a sequencing option this plan thought it had. An earlier draft
said "lowering the floor and enabling a flat-text format must not land in the
same release without the filename rules in between", treating the floor as a
lever to time. It is not a lever any more — in code the floor is already 1KB,
so the moment a flat-text format can be enabled, `readme.txt` and `license.txt`
are eligible on any install that has picked up the new default. **The filename
rules are therefore a prerequisite of Phase 6, not a companion to it**, and
they should land in Phase 2 as planned regardless of when TXT/MD/RTF arrives.

## Codex eligibility

**What Codex is for:** sharing identifications of content that can be
purchased somewhere else — adventures, sourcebooks, zines and other play aids.
It is not for collections of images or maps.

**Codex is PDF-only, and that is a standing rule rather than a starting
position** (confirmed 2026-08-24). Nothing but a PDF is ever contributed
upstream, in this release and every release after it — the multi-format work
extends what Grimoire will *catalogue*, and changes nothing about what
Grimoire will *share*. A later phase adding CBZ or RTF does not get to revisit
this; it inherits it.

Two independent rules, then, both outbound-only: the file must be a PDF, and
its content must not be images or maps. Reading *from* Codex
(`sync_product_from_codex`, enrichment, identification) stays enabled for
every product regardless, since it sends nothing upstream.

A single predicate, so the rule lives in one place:

```python
# grimoire/services/sync_service.py
def is_codex_eligible(product: Product) -> tuple[bool, str]:
    if product.file_type != "pdf":                    # ← added in Phase 2 here
        return False, "unsupported_file_type"
    if product.is_image_content:                      # ← realignment Phase 3
        return False, "image_content"
    if product.product_type in IMAGE_PRODUCT_TYPES:   # "Art/Maps", "Map", ...
        return False, "image_content"
    return True, "eligible"
```

⚠️ **The two clauses cannot land together.** `file_type` does not exist on
`Product` until Phase 2 of *this* plan, so the realignment plan — which lands
first — ships the predicate with its image/map clauses only, and Phase 2 here
adds the `file_type` clause and its test in the same commit that adds the
column. Anything else is a circular dependency between the two plans.

Called from two places, because there are two ways into the queue:

- `should_contribute` (`services/sync_service.py:116`) — the automatic path.
  Check before the Codex hash lookup, so an ineligible product never costs a
  network round trip.
- `queue_contribution` (`services/contribution_service.py:99`) — the single
  choke point every queued contribution passes through, including the manual
  route (`api/routes/contributions.py:95`), the product-update path
  (`api/routes/products.py:370`) and `queue_local_edit_for_sync`
  (`sync_service.py:600`).

The second is a genuine backstop rather than belt-and-braces:
`queue_product_for_contribution` takes `skip_no_change_check=True`
(`sync_service.py:467-471`), which skips `should_contribute` altogether. A guard
placed only there is bypassable by an existing parameter. It is also a real
choke point — `ContributionQueue` is constructed in exactly one place
(`contribution_service.py:109`), reached from `sync_service.py:535`, `:600`
and `api/routes/contributions.py:95`.

One wrinkle for whoever writes it: `queue_contribution` takes `product_id: int`,
not a `Product`, so the predicate as drafted above cannot be called there
without loading the row first. Widen it to accept an id, or load once at the
top of the function — but do not move the check out to the three callers, since
being the single place they all pass through is the whole reason it is the
backstop.

`api/routes/contributions.py` returns a 422 naming the reason rather than
silently succeeding, and the frontend hides the contribute action on
ineligible products instead of surfacing a button that always fails.

### Pre-existing gap

There is currently **no `is_image_content` check anywhere in the contribution
path** — not in `should_contribute`, `queue_contribution`,
`queue_product_for_contribution` or the API route. A map pack or stock-art PDF
that has been given a title is contributable to Codex today, which the image
classifier's own `Art/Maps` classification says it should not be.

This predates the multi-format work and is a bug on its own merits. It is
**owned by `2026-08-23-codex-contract-realignment.md` Phase 3**, which lands
before this feature — that review found the Grimoire↔Codex read path is
currently broken as well, and the eligibility predicate belongs with the rest
of the Codex work rather than being duplicated here. This plan adds one clause
to it (`file_type`) in Phase 2 and otherwise leaves it alone.

## Discovery

Four sites glob for PDFs and all must consult the registry:

- `services/scanner.py:73` — `rglob("*.pdf")`
- `services/batch_scanner.py:71` — `discover_files`
- `services/watcher.py:62` — suffix check on filesystem events
- `services/exclusion_service.py:268` — rule-preview walk

Replace with a single walk matching an extension set. **Performance
constraint:** the current single-pattern `rglob` was chosen for large network
folders. Walk once with `os.scandir`-based recursion and match against the
enabled set — do **not** loop `rglob` once per extension, which multiplies
directory traversals by the format count over an SMB mount.

`scan_folder`'s return dict should gain a per-format breakdown so the scan
summary can report "412 PDF, 18 EPUB, 3 DOCX".

## Frontend

- `file_type` filter chip in Library alongside the existing filters.
- Format badge on cards whose `file_type != "pdf"`.
- **Reader view**: `PDFViewer.tsx` (react-pdf) stays PDF-only. Non-PDF
  products get a reader that renders the extracted markdown from the existing
  text endpoint — pageable using the synthetic `pages` array, so the same
  navigation UI works. Anything not yet text-extracted offers download only.
- `GET /products/{id}/pdf` (`api/routes/products.py:560`) hardcodes
  `media_type="application/pdf"`. Either add a `/file` route that maps
  extension → media type, or generalise this one and keep `/pdf` as an alias
  so existing frontend calls and any bookmarks keep working.

---

## Phasing

Each phase ships independently and leaves the app working.

> **Where the work happens:** the real library is on Michael's home computer;
> this laptop has a sample `pdfs/` folder. Phases 1–4 are code-and-tests and
> run anywhere. Scan performance over a large folder, and the first real
> multi-format scan, must be verified on the home machine — see the same
> split in the Codex realignment plan.

**Phase 1 — registry + PdfHandler.** No behaviour change, no new formats.
Move existing PDF code behind the protocol, dispatch all six call sites.
*This is where the entire risk of the feature lives.* Existing test suite must
pass unchanged (against the six known pre-existing failures on main).

**Phase 2 — `file_type` column, migration, generalised discovery, settings
toggle.** Still PDF-only in effect: default `["pdf"]` means no user sees a
change. Per-format scan counts in the summary. **Also completes
`is_codex_eligible`**: the `file_type != "pdf"` clause goes in with the column,
since the realignment plan's Phase 3 could not carry it. **Also the exclusion
work**: the five filename rules and the idempotent migration that puts them —
and the already-shipped 1024 `size_min` default — onto installs seeded before
`834d4e8`. See [Opt-in per format](#opt-in-per-format).

⚠️ **Commit order inside this phase is load-bearing.** The `file_type` clause
of `is_codex_eligible` must land in the same commit as the column, or ahead of
generalised discovery — never after it. The column is what makes a non-PDF
`Product` expressible and discovery is what creates one; the instant both exist
without the clause, a non-PDF product can reach the contribution queue. There
is no window in which that is acceptable (see
[Codex eligibility](#codex-eligibility)), and it is invisible in testing
because the default `["pdf"]` means nobody has a non-PDF product to catch it
with.

**Phase 3 — EPUB.** Exercises the full happy path: real metadata, embedded
cover, synthetic pagination, search, embeddings, bestiary.

**Phase 4 — DOCX + ODT.** Exercises the placeholder-cover path and
metadata-poor documents.

**Phase 5 — frontend.** Filter, badge, markdown reader, file route.

**Phase 6 (separate request) — TXT / MD / RTF**, plus `charset-normalizer`
for encoding sniffing. Deliberately after the machinery is proven, because
these carry the highest junk-file risk and the least metadata.

**Out of scope:** legacy `.doc` (needs LibreOffice/antiword shell-out), MOBI/AZW
(DRM), CBZ/CBR, and any change to the PDF extraction quality path.

**Also out of scope, and worth naming because it is adjacent enough to get
confused with this work: archive bundles.** There are roughly 3,139 `.zip`
files under the library that the scanner has never looked inside — it globs
`*.pdf` and always has. This plan does not open them. It is tempting to treat
"scan more formats" as covering it, but an archive is a container rather than a
document: it needs a decision about whether one zip is one product or many,
where extracted members live, and what happens on rescan. That is its own
spec. The one thing this plan should not do is make it *harder* — `get_handler`
dispatches on extension, so a future `ZipHandler` that yields inner documents
fits the registry without reshaping it.

## Tests

Following the TDD workflow in AGENTS.md, and mirroring `tests/pdf_fixtures.py`:

- `tests/format_fixtures.py` — builds minimal valid EPUB/DOCX/ODT in a tmpdir
  (all three are zip containers; no binary fixtures need committing).
- `tests/formats/test_registry.py` — dispatch, unknown extension, disabled format.
- `tests/formats/test_epub.py` / `test_docx.py` / `test_odt.py` — the seam-1
  dict shape, metadata mapping, cover presence/absence.
- `tests/formats/test_pagination.py` — chunk boundaries, chapter splitting,
  `pagination` marker.
- `tests/formats/test_placeholder_cover.py` — file written, dimensions, no
  system-font dependency.
- `tests/services/test_scanner_multiformat.py` — disabled formats are not
  discovered; enabled ones are; single-walk behaviour.
- Regression: an EPUB never enters the `ocr_text` or `extract_images` branch.
- `tests/services/test_codex_eligibility.py` — most of this file belongs to
  the realignment plan (image/map rejection, both call sites,
  `skip_no_change_check=True` still cannot get an ineligible product queued,
  the manual API route's 422). Phase 2 here adds the non-PDF cases: a non-PDF
  product is rejected, and inbound `sync_product_from_codex` remains
  unaffected for non-PDF.
- Regression: a fresh install and an upgraded install both default to
  `["pdf"]`, and registering a new handler does not change that.

Run via the Docker image (torch lives in requirements).

## Acceptance criteria

- [ ] Existing PDF behaviour is byte-identical through phases 1–2
- [ ] An EPUB scans, gets its embedded cover, its OPF metadata, full-text and
      semantic search, and AI identification
- [ ] A DOCX scans, gets a legible placeholder cover, and is searchable
- [ ] With default settings, an existing user's rescan finds exactly what it
      found before
- [ ] Scan summary reports counts per format
- [ ] An upgraded install gets the new filename exclusion rules and the 1KB
      `size_min` without losing rules the user disabled or edited, and running
      the migration twice changes nothing the second time
- [ ] No non-PDF document is ever routed to OCR or image-content classification
- [ ] No non-PDF product, and no image/map product, can reach the Codex
      contribution queue by any route — including `skip_no_change_check=True`
- [ ] Inbound Codex enrichment still works for non-PDF products
- [ ] Library filter by format, and a working reader for non-PDF documents

## Open questions

1. Should EPUB chapters map to `pages`, or should the bestiary/citation UI
   learn a separate "section" concept? Current plan reuses `pages` with a
   `pagination` marker — cheapest, slightly lossy in naming.
2. Should a DOCX/ODT placeholder cover be regenerated if the user later edits
   the document title, or is it fire-and-forget at scan time?
3. *(resolved — the eligibility guard is Phase 3 of the Codex contract
   realignment plan, landing before this feature, with its `file_type` clause
   added by Phase 2 here.)*
