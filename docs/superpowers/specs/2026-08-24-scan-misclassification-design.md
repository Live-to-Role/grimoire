# Scanned Documents Misclassified as Image Content — Design

Status: approved
Date: 2026-08-24
Follows: `backend/docs/superpowers/specs/2026-07-13-image-file-filtering-design.md`,
which deliberately left "reworking the confirmation thresholds" out of scope.

## Problem

Scanned adventure modules are catalogued as collections of images and never
text-extracted. The user found five in the Gallery — three Star Frontiers
modules, a Ravenloft supplement and a Planescape sourcebook — and asked whether
the scans were too poor to OCR.

They are not. Measured 2026-08-24 on the real library:

| File | Text layer | Image resolution | OCR (one page) |
|---|---|---|---|
| SF1 Volturnus Planet of Mystery | 0 chars | 5101×6578 (~600 DPI) | 6,322 chars / 923 words |
| On Hallowed Ground | 0 chars | 1203×1584 (~142 DPI) | 6,097 chars / 868 words |

Both produce clean prose. Nothing had judged them poor because nothing had
tried: `text_extracted=0`, `text_unextractable=0`, `extraction_error=NULL`.
They were routed to image extraction instead.

### Root cause

`image_classifier.py:205`, the branch taken when a filename carries no signal:

```python
if image_page_ratio >= 0.9 and content["avg_chars_per_page"] < 20:
    return {"is_image_content": True, ...}
```

A scanned book has no text layer, so **every page reads as image-dominant with
zero characters** — exactly this test. On these two numbers an art pack and a
scanned module are indistinguishable. Every affected product shows the
signature of one full-page image per page (SF1 Volturnus 36pg/36img, On
Hallowed Ground 195pg/195img).

### Scale

| | Count |
|---|---|
| Flagged `is_image_content` | 1,710 |
| With the scan signature (images ≈ pages) | 971 |
| …over 20 pages | 285 |
| …never text-extracted | 95 |

### Consequences

- Scanned books are invisible to full-text search, semantic search, the
  bestiary and AI identification.
- As of `46fb26e` (Codex realignment Phase 3), `is_image_content` products are
  **ineligible to contribute to Codex**. Correct for art packs; for these
  scans it is a second wrong answer built on the first.

## Why this is manual, not automatic

An earlier draft proposed an OCR probe: sample pages, count words, decide
automatically. **It was measured and rejected.** Medians over a hand-labelled
sample of 15 products:

| Scans (10) | Packs (5) |
|---|---|
| 812, 601, 601, 541, 403, 399, 353, 292, 246, **175** | **176**, 26, 0, 0, 0 |

*Planes of Chaos*, a real scan, scores 175. *CR1 Wizard Spell Cards*, a card
deck, scores 176. The populations invert. A max-based statistic separated this
particular sample (scan minimum 386 vs pack maximum 217), but on 15 products —
only 5 of them packs, the side that sets the boundary — that is a threshold
fitted to its own validation set.

The deciding argument is that the overlap is **not noise**. Card decks carry
real rules text; that is what a card is. Any statistic that reliably sorts them
away from scanned books is measuring something other than word count, and the
user's eye does the job in one glance.

**Decision: no probe, no threshold, no automatic backfill.** ~971 products is a
reviewable number. The classifier is left as it is.

⚠️ **Standing cost of that decision:** newly scanned books will keep being
misclassified the same way. This is self-correcting only because they land in
the Gallery, which is where review happens. The root cause is documented above
and remains open.

## Design

### 1. Two new columns

**`is_scanned`** (boolean). `is_image_content` means "a collection of images";
`is_scanned` means "a document whose pages are images". Different facts,
currently conflated. `is_scanned` survives the image flag being cleared, so it
drives the OCR route, shows a Gallery badge, and decides whether artwork may be
shared (§4).

**`classification_reviewed_at`** (nullable datetime). Records that a human
judged this product, whichever way they judged it. Without it there is no way
to tell page 12 of the backlog from page 30, and re-covering ground is the main
cost of reviewing ~971 items.

Both added through `_ensure_columns` like the rest.

### 2. Gallery review workflow

The Gallery is a product grid (`Gallery.tsx`, 24/page) opening a per-product
image modal. It has no selection state.

- Checkbox on each `GalleryCard`.
- Sticky action bar when any are selected, with **two** actions:
  `Mark as scans` · `Confirm as images` · `Clear`.
- **A "needs review" filter, on by default.** The grid shows only products with
  `classification_reviewed_at IS NULL`, so the backlog visibly shrinks as it is
  worked through.
- Cards show a `36pg / 36img` hint. That ratio is the strongest visual tell and
  is what distinguishes SF1 Volturnus from an 864-page card deck at a glance.

Both actions stamp `classification_reviewed_at`. **`Confirm as images` is not a
no-op** — it is what removes a correctly-classified pack from the queue, and
without it the filter never empties.

Multi-select was chosen over a per-card button or a modal-only action because
the backlog is ~971 items: sweeping a page of 24 and applying once is the only
shape that scales.

### 3. Un-flagging finally queues extraction

The existing bulk path (`bulk.py:288-311`) clears the flag, nulls
`product_type`, deletes the extracted images from disk and removes content-type
tags — but **never queues text extraction**. Today un-flagging loses the images
without gaining the text.

Destructive semantics stay as they are (user decision: one code path,
consistent with the Library). Defensible on the data: of the 285 suspected
scans, 121 are typed `Map` — wrong, worth clearing — and 93 are already `NULL`.
Only ~56 carry a plausibly correct type.

The change is that this path now sets `is_scanned` and enqueues `ocr_text`,
fixing the Gallery action and the existing Library button together.

**Safety net:** if OCR returns nothing, the existing `text_unextractable`
disposition catches it. A wrong call costs one extraction pass and flags
itself, which is what makes manual review safe to be approximate.

### 4. Cover-image contribution rules

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
otherwise be the first one uploaded, which is the case of concern.

Neither rule blocks the contribution; both drop only the image.

## Out of scope

- **Fixing the classifier.** Deliberate, per the decision above.
- Zip-archive scanning (~3,139 unscanned archives) — still its own spec.
- Improving OCR *quality*, as opposed to routing scans to OCR at all.
- Re-running Codex contribution for rescued scans. They become eligible, but
  nothing re-offers them automatically.
- Anything already uploaded to Codex. These rules govern what Grimoire sends
  from now on; existing contributions are a separate cleanup.

## Testing

- **Columns**: `_ensure_columns` adds both; an existing database gains them
  without losing data; running twice is a no-op.
- **Bulk un-flag**: sets `is_scanned`, enqueues `ocr_text`, and stamps
  `classification_reviewed_at` — from both the Gallery and Library paths. The
  enqueue is the part that does not exist today.
- **Confirm as images**: stamps `classification_reviewed_at` and changes
  nothing else. Specifically: does not clear `is_image_content`, does not
  enqueue extraction.
- **Needs-review filter**: a reviewed product leaves the default grid; an
  unreviewed one stays; the filter can be turned off to see everything.
- **Cover rules**: a scanned product contributes metadata with no
  `cover_image_base64`; a product whose Codex match has a `cover_url` likewise;
  an ordinary product with no Codex cover still sends one.
- **Gallery**: selection state, both action shapes, the `pg/img` hint.

## Acceptance criteria

- [ ] The five products named by the user can be marked from the Gallery and
      end up text-extracted and searchable
- [ ] Marking a product as a scan from either the Gallery or the Library
      results in extracted text
- [ ] Confirming a pack as images removes it from the needs-review grid and
      does nothing else
- [ ] The needs-review count falls monotonically as review proceeds, and
      survives a page reload
- [ ] No contribution carries a cover image for a scanned product, or for a
      product Codex already has a cover for
- [ ] A rescued scan becomes Codex-eligible again
- [ ] A product whose OCR returns nothing is marked `text_unextractable`
      rather than retried indefinitely
