# Scanned Documents Misclassified as Image Content — Design

Status: approved
Date: 2026-08-24
Follows: `backend/docs/superpowers/specs/2026-07-13-image-file-filtering-design.md`,
which deliberately left "reworking the confirmation thresholds" out of scope.
This is that work.

## Problem

Scanned adventure modules are being catalogued as collections of images and
never text-extracted. The user found five in the Gallery — three Star Frontiers
modules, a Ravenloft supplement and a Planescape sourcebook — and asked whether
the scans were too poor to OCR.

They are not. Measured 2026-08-24 on the real library:

| File | Text layer | Image resolution | OCR result (one page) |
|---|---|---|---|
| SF1 Volturnus Planet of Mystery | 0 chars | 5101×6578 (~600 DPI) | 6,322 chars / 923 words |
| On Hallowed Ground | 0 chars | 1203×1584 (~142 DPI) | 6,097 chars / 868 words |

Both produce clean, readable prose. Nothing had ever judged them poor, because
nothing had ever tried: `text_extracted=0`, `text_unextractable=0`,
`extraction_error=NULL`. They were routed to image extraction instead.

### Root cause

`image_classifier.py:205`, the branch taken when a filename carries no signal:

```python
if image_page_ratio >= 0.9 and content["avg_chars_per_page"] < 20:
    return {"is_image_content": True, ...}
```

A scanned book has no text layer, so **every page reads as image-dominant with
zero characters**. It matches this test perfectly. The comment calls it
"overwhelming evidence", but the evidence is equally consistent with a scan: on
these two numbers an art pack and a scanned module are indistinguishable.

Every affected product shows the signature — one full-page image per page:

| Product | pages | images |
|---|---|---|
| SF1 Volturnus | 36 | 36 |
| SFKH4 The War Machine | 38 | 38 |
| SF4 Mission to Alcazzar | 38 | 38 |
| Children of the Night — Werebeasts | 99 | 98 |
| On Hallowed Ground | 195 | 195 |

### Scale

| | Count |
|---|---|
| Flagged `is_image_content` | 1,710 |
| With the scan signature (images ≈ pages) | 971 |
| …over 20 pages | 285 |
| …never text-extracted | 95 |

**Page count alone cannot separate them.** The largest flagged products are
genuinely mixed: *Planes of Chaos* (257pg), *City of Greyhawk Boxed Set*
(250pg), *Ruins of Myth Drannor* (230pg) and *Bleak House* (206pg) are real
scans, while *CR3 Deck of Magical Items* (864pg), *CR1 Wizard Spell Cards*
(854pg) and *Fantasy Art Subscription* (201pg) are correctly classified. An
864-page card deck *is* image content.

The only reliable discriminator is what OCR actually returns: a scanned book
yields hundreds of words per page, a card deck a handful.

### Consequences

- Scanned books are invisible to full-text search, semantic search, the
  bestiary and AI identification.
- As of `46fb26e` (Codex realignment Phase 3), `is_image_content` products are
  **ineligible to contribute to Codex**. For genuine art packs that is correct;
  for these scans it is a second wrong answer built on the first.

## Design

### 1. The classifier stays fail-safe

The ambiguous branch keeps flagging exactly as it does today, and additionally
enqueues a `classify_probe` task that can reverse it. Reaching that branch is
itself the record that the decision was a guess — see §3.

Deliberately *not* "stop flagging and let text extraction decide". Two reasons.
Nothing regresses if the probe never runs or is disabled — the behaviour without
a probe is today's behaviour. And the product keeps its Gallery entry with
extracted images, which is both the prior spec's stated intent ("the user keeps
a searchable gallery entry") and the surface the user reviews these on.

### 2. A `classify_probe` queue task

Queue task types are free-text with a handler per name (`handle_text_task`,
`handle_ocr_text_task`, …); this adds one more in the same shape.

- Render three pages at 20%, 50% and 80% depth. Sampling by depth skips the
  cover and front matter, which are legitimately text-light and would drag a
  mean toward "image".
- OCR each, take the **median** words per page — one plate in the middle of a
  book should not swing the verdict.
- **Above `SCAN_WORDS_PER_PAGE`** → a document: clear `is_image_content`, set
  `is_scanned`, enqueue `ocr_text`.
- **Below** → confirm image content. Either way the probe stamps
  `classification_probed_at` (§3) so it is not repeated.

⚠️ **The threshold is the one number that decides everything, and it is
currently a guess.** Observed: 923 and 868 words/page on two real scans; a card
deck page is estimated at 20–60 and has not been measured. Start at 100, and
**validate against a hand-labelled sample of at least 20 products before the
backfill runs** — roughly ten known scans and ten known image packs drawn from
the lists above. If the two populations do not separate cleanly, the threshold
is the wrong instrument and the design needs revisiting before 971 products
move.

### 3. Two new columns

**`is_scanned`** (boolean). `is_image_content` means "a collection of images";
`is_scanned` means "a document whose pages are images". These are different
facts and the codebase currently conflates them. `is_scanned` survives the
probe clearing the image flag, so it can drive the OCR route, show a Gallery
badge, and — see §6 — decide whether artwork may be shared.

**`classification_probed_at`** (nullable datetime). This is the concrete
mechanism behind "the decision was a guess" and "do not probe twice", which
would otherwise be hand-waving:

| `is_image_content` | probe queued | `classification_probed_at` | Meaning |
|---|---|---|---|
| true | no | NULL | Confident — filename or publisher signal decided it |
| true | yes | NULL | Guessed, probe pending |
| either | — | set | Probe has run; its verdict stands |

Only products reaching the ambiguous branch ever get a probe queued, so
"guessed" needs no separate flag. A non-NULL timestamp makes the backfill
idempotent — re-running it enqueues nothing for products already probed, which
is what the "runs twice changes nothing" criterion depends on.

A manual Gallery flag also sets `classification_probed_at`, so a human verdict
is never second-guessed by a later probe.

Both added through `_ensure_columns` like the rest.

### 4. Gallery multi-select

The Gallery is a product grid (`Gallery.tsx`, 24/page) opening a per-product
image modal. It has no selection state.

- Checkbox on each `GalleryCard`.
- Sticky action bar when any are selected: `N selected · Mark as scans · Clear`.
- Cards show a `36pg / 36img` hint. That ratio is the strongest visual tell and
  is what distinguishes SF1 Volturnus from an 864-page card deck at a glance.

Chosen over a per-card button or a modal-only action because the backlog is 971
items: sweeping a page of 24 and applying once is the only shape that scales.

### 5. Un-flagging finally queues extraction

The existing bulk path (`bulk.py:288-311`) clears the flag, nulls
`product_type`, deletes the extracted images from disk and removes content-type
tags — but **never queues text extraction**, so today un-flagging loses the
images without gaining the text.

The destructive semantics stay as they are (user decision: one code path,
consistent with the Library). This is defensible on the data: of the 285
suspected scans, 121 are typed `Map` — wrong, worth clearing — and 93 are
already `NULL`. Only ~56 carry a plausibly correct type.

The one change is that this path now enqueues `ocr_text`, which fixes the
Gallery action and the existing Library button together.

### 6. Cover-image contribution rules

Grimoire sends `cover_image_base64` on every contribution
(`build_contribution_data`, `include_cover=True` by default). Many of these
scans came from a third party years ago and their provenance cannot be
established. Metadata is factual and remains contributable; artwork is the
publisher's.

Two rules, covering different halves:

- **Never send a cover Codex already has.** `should_contribute` already fetches
  the match and inspects `codex_product.cover_url`, then discards it. Capture
  it and pass `include_cover=False`. Cuts cover uploads across the whole
  library.
- **Never send a scanned product's cover.** A `may_share_cover(product)`
  predicate beside `is_codex_eligible`, keyed on `is_scanned`.

The second is not redundant: the first keys on Codex *already having* a cover,
so for a `new_product` — where Codex knows nothing — a scan's cover would
otherwise be the first one uploaded, which is exactly the case of concern.

Neither rule blocks the contribution; both drop only the image.

### 7. Backfill

A Library Management button enqueuing `classify_probe` for all 1,710 flagged
products, reusing the same queue path as new scans rather than a one-off
script. At a few seconds each this is roughly an hour in the background.

⚠️ Gated on the threshold validation in §2. The backfill will move ~971
products out of the Gallery, which is a large and visible change; getting the
threshold wrong is expensive to undo.

## Out of scope

- Zip-archive scanning (~3,139 unscanned archives) — still its own spec, per
  the prior design.
- Improving OCR *quality* for scans, as opposed to routing them to OCR at all.
- The reverse correction (an art pack the probe wrongly rescues). It leaves the
  Gallery, so it cannot be re-flagged from there; the Library bulk edit already
  handles it.
- Re-running Codex contribution for products the probe rescues. They become
  eligible, but nothing re-offers them automatically.

## Testing

- **Classifier**: a scanned-book fixture and an art-pack fixture both reach the
  ambiguous branch; both are flagged; both enqueue a probe.
- **Probe**: high-text sample clears `is_image_content`, sets `is_scanned` and
  enqueues `ocr_text`; low-text sample confirms image content and does not
  re-probe. Median-of-three ignores a single text-heavy plate.
- **Sampling**: pages are drawn by depth, not from the front — a fixture whose
  first three pages are a blank cover must still be recognised.
- **Bulk un-flag**: enqueues text extraction (currently missing), from both the
  Gallery and Library paths.
- **Cover rules**: a scanned product contributes metadata with no
  `cover_image_base64`; a product whose Codex match has a `cover_url` likewise;
  an ordinary product with no Codex cover still sends one.
- **Gallery**: selection state, bulk call shape, the `pg/img` hint.
- **Threshold validation** is a measurement, not a unit test: a script over the
  labelled sample, reported before the backfill is run.

## Acceptance criteria

- [ ] The five products named by the user are text-extracted and searchable
- [ ] `CR3 Deck of Magical Items` and `Fantasy Art Subscription` remain image content
- [ ] The threshold is validated against ≥20 labelled products, and the two
      populations separate cleanly, before any backfill
- [ ] Un-flagging a product from either the Gallery or the Library results in
      extracted text
- [ ] No contribution carries a cover image for a scanned product, or for a
      product Codex already has a cover for
- [ ] A rescued scan becomes Codex-eligible again
- [ ] Running the backfill twice changes nothing the second time
