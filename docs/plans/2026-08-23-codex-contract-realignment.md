# Codex Contract Realignment — Phased Plan

Status: draft for review
Date: 2026-08-23
Blocks: `2026-08-23-multi-format-scanning-design.md` (Codex eligibility work)

## Verdict

**Outbound contributions are still compatible. Inbound enrichment is broken.**

Every field Grimoire's `build_contribution_data` sends is either in Codex's
`EDITABLE_FIELDS` (`catalog/contributions.py:55`) or handled by the apply path
as a composite/derived field, and the envelope Grimoire's client posts
(`contribution_type`, `data`, `file_hash`, `source: "grimoire"`,
`Authorization: Token`) is exactly what `ContributionCreateSerializer`
expects. That path works and needs no emergency fix.

⚠️ An earlier draft credited this to a constant named `ALLOWED_PRODUCT_FIELDS`,
which does not exist in Codex — the same phantom-symbol mistake this plan
catches elsewhere with `LEGACY_SIZE_MIN_PATTERN`. The conclusion survives the
correction but the reasoning needed redoing, because `EDITABLE_FIELDS` is
*narrower* than the name it replaced suggests: it does **not** contain `author`,
`genre`, `publisher`, `game_system`, `series`, `series_order` or
`publication_year`, all of which Grimoire sends. Each is handled separately and
deliberately — `author`/`authors` and `genre`/`genres` are normalised to lists
and merged (`contributions.py:305-309`, `:414-425`), `series` resolves through
`_resolve_series` (`:112`, `:318`, `:433`), and `publication_year` is coerced by
`_coerce_publication_date` (`:86-99`), which reads `publication_date` first and
falls back to the year. Verified field by field against Codex `main`; nothing
Grimoire sends is silently dropped.

The read path does not. Codex's `/identify` now returns
`ProductDetailSerializer`, which **no longer has `author`, `genre`,
`publication_year`, `dtrpg_url` or `game_system_slug`**, and returns
`publisher` and `game_system` as **nested objects rather than strings**.
Grimoire's `CodexProduct.from_dict` (`services/codex.py:60`) still reads all
of those as flat values.

---

## Finding 1 — Codex enrichment writes a dict into a string column (severity: high)

`sync_product_from_codex` (`services/sync_service.py:230`) maps
`codex_product.publisher` straight onto `Product.publisher`, which is
`String(255)`:

```python
field_mappings = [
    ("publisher", codex_product.publisher),      # now a dict
    ("game_system", codex_product.game_system),  # now a dict
    ("publication_year", codex_product.publication_year),  # now always None
    ...
]
```

The loop skips a `None` and only writes when `overwrite_existing or not
current_value` (`:244-253`), so the precise trigger is *a matched product
whose local field is blank* — which, under `sync_all_products`' default
`only_unidentified=True`, is very nearly all of them. There, `publisher` and
`game_system` bind a `dict` to a VARCHAR parameter. Under aiosqlite that is an
`InterfaceError`, not a silent coercion — so enrichment does not degrade, it
raises, and it raises only for products Codex *does* know, which are the
ones the feature exists to serve.

⚠️ **And it takes the rest of the run with it.** `sync_all_products` catches
per product and continues (`:329-331`) but never calls `db.rollback()`. The
`InterfaceError` surfaces inside `await db.commit()`, which leaves the
`AsyncSession` inactive; every subsequent statement raises
`PendingRollbackError`. So the first matched product does not fail alone — it
poisons the session and every product after it is counted as `failed`. The
summary reports a total collapse rather than one bad row, which is worth
knowing before Phase 0 tries to interpret a traceback.

Fields that silently became no-ops, because Codex no longer sends the key:

| Grimoire reads | Codex now sends |
|---|---|
| `author` | — (`credits`, a list of credit objects) |
| `genre` | — (`themes`, `tags`) |
| `publication_year` | `publication_date` (ISO string) |
| `dtrpg_url` | `dtrpg_id` + `links[]` |
| `game_system_slug` | inside the nested `game_system` object |

⚠️ **`sync_product_from_codex` is not the only reader, and the second one is
easy to miss.** `check_for_updates` (`services/sync_service.py:344`) builds its
own `field_mappings` at `:368` — `title`, `publisher`, `game_system`,
`product_type`, `publication_year` — and compares `current_value !=
codex_value` without ever writing. No commit, so no `InterfaceError`; instead
**every matched product now reports `publisher` and `game_system` as
differing**, with a nested dict rendered as the "Codex" side of the diff in the
update-check UI. Quieter than Finding 1's failure and longer-lived, because
nothing raises.

This decides *where* the Phase 1 fix goes. That phase currently offers two
remedies — reshape `CodexProduct.from_dict`, or add a type guard to
`sync_product_from_codex`'s mapping loop. Only the first covers this site. **Do
both, in that order of importance:** `from_dict` is the fix, and the type guard
is a backstop against the next reshape, not an alternative to it.

**This wants verifying against the live API before anything is rewritten** —
the serializer is unambiguous, but a stale deployment would change the
priority. See Phase 0.

## Finding 2 — benign Codex outcomes are recorded as permanent failures

`submit_contribution` (`services/contribution_service.py:132`) treats any
non-2xx as `ContributionStatus.FAILED` with the raw body as the error. Two
of Codex's ordinary outcomes are 400s:

- `duplicate_pending` — "a pending contribution with this file hash already
  exists". Entirely benign; Grimoire already sent it. Recorded as a failure,
  and `existing_contribution_id` is discarded.
- `no_change` — returns **200** with `status: "no_change"`, so Grimoire marks
  it `SUBMITTED`. Harmless but wrong: nothing was submitted, and
  `existing_product_id` — a free link between the local product and the Codex
  one — is thrown away.

## Finding 3 — `warnings` are dropped, and they are Grimoire's only visibility

This is worse than it first looks, because of how Codex now treats a Grimoire
sync.

`GRIMOIRE` and `API` are **guarded sources** (`catalog/merge_rules.py:179`).
A guarded sync fills blanks and unions lists, but **never replaces a value
somebody curated on Codex**. When the two disagree, `guard_changes` *deletes
the key from the payload* — "a key that would overwrite is removed, not
blanked" — records a `HeldBack`, and the apply then writes nothing for that
field. The response is still `status: "applied"`.

So a Grimoire sync whose description and product_type both differ from
Codex's reports success while writing neither. The `warnings` array is the
only channel that says so, and `ContributionResult.from_response`
(`services/codex.py:129`) does not read it. Codex's own comment is explicit
that this was the point: "a refusal nobody can see is its own bug."

The guard is right, and Grimoire should not try to defeat it. But Grimoire
currently cannot tell a full apply from one that was almost entirely held
back, which makes "did my library actually sync?" unanswerable.

⚠️ **On the queued path the warnings are not merely unread — they are
destroyed.** Codex's `approve_contribution`
(`catalog/contributions.py:565`) appends them to `contribution.review_notes`
in memory and leaves saving to the caller, and both API review paths then
assign the moderator's own `review_notes` (default `""`) over the top before
saving — single review at `api/views_contributions.py:501-511`, batch review
at `:544-555`. Only the Django-admin actions preserve them. So reading
`review_notes` back, which is what Phase 2's polling is for, returns nothing
on the route moderators actually use. **This is a Codex-side fix and it is a
prerequisite of Phase 2**; it is written into
`codex/docs/GRIMOIRE_MODERATION_PARITY_PLAN.md` Phase 1. Until it lands,
polling can resolve a contribution's *status* but not learn what was held
back.

## Finding 4 — Grimoire is on the legacy ingest path

Codex marks `dtrpg_url` / `itch_url` as *legacy ingest keys* — "the columns
are gone; these are still accepted because Grimoire sends both on every sync"
— and folds them into `links` on apply. Grimoire also never sends:

| Field | What Grimoire loses |
|---|---|
| `links` | labelled multi-store links, affiliate flags; itch/DTRPG are all it can express |
| `dtrpg_id` | the marketplace id Codex dedupes and searches on, and `/identify`'s most reliable lookup — checked *before* hash |
| `game_systems` (plural) | a product written for several systems |
| `authors`, `genres` (plural) | multiple authors/genres |
| `ai_disclosure` | cannot declare AI involvement (`human` / `ai_generated` / `tool_assisted`) |

None of this is breaking. It is accumulating drift, and `dtrpg_id` is the one
with real value: Codex's own comment says an importer told "no match" because
a scan did not reach far enough is how 919 duplicate products appeared.

## Finding 5 — `/identify` is rate-limited

`IdentifyView` carries `throttle_classes = [IdentifyRateThrottle]`.
`sync_all_products` walks the library calling `identify_by_hash` per product
with no backoff and no 429 handling.

The limit is **60 requests per minute**, and `IdentifyRateThrottle` subclasses
`AnonRateThrottle` (`codex/backend/apps/core/throttling.py:34`) — so the bucket
is keyed by **IP, not by token**, and every client behind one address shares it.
A first sync over the real library is the request pattern most likely to hit it,
and this is exactly the case that cannot be exercised on the dev laptop.

⚠️ **The ceiling exists only because Grimoire calls `/identify` anonymously.**
`AnonRateThrottle.get_cache_key` returns `None` for an authenticated request —
it throttles anonymous callers and nobody else. `identify_by_hash` and
`identify_by_title` (`services/codex.py:257`, `:294`) send no `Authorization`
header, which is the entire reason the limit applies to us. `IdentifyView` is
`AllowAny`, so adding the token we already hold removes the constraint outright.

**Decided (2026-08-24): authenticate `/identify`, and pace the walk anyway.**
Both halves, deliberately:

- **Authenticate.** Send the token on `identify_by_hash` and
  `identify_by_title`. The throttle stops applying, and Grimoire stops sharing
  an IP-keyed bucket with every other anonymous caller behind the same address
  — which was never a limit on *us* so much as a limit on our neighbours.
- **Keep a modest client-side pace regardless.** Phase 5 walks the whole real
  library in one pass; that it is now *permitted* to do so at full speed is not
  a reason to. Pacing is a few lines, it is the difference between a good
  neighbour and a self-inflicted incident on a service Michael also runs, and
  it survives Codex changing its mind about throttling later.

This closes the trap the earlier draft flagged — that Phase 4's `dtrpg_id` work
might add a token header for consistency and silently disarm a backoff written
in Phase 2. Both are now intentional and neither depends on the other.

**The throttle was never the dangerous part, though.** See the swallowed-error
bug immediately below: it is what turns a failed lookup into a duplicate
contribution, and it must be fixed whether or not the ceiling can still be
reached. Authenticating makes the trigger rarer; a timeout or a 500 pulls it
just as hard.

⚠️ **A throttled lookup does not fail — it reports "new product".**
`identify_by_hash` wraps `response.raise_for_status()` in
`except Exception: return None` (`services/codex.py:246-272`), and
`should_contribute` reads a `None` match as `return True, "new_product"`
(`services/sync_service.py:138-140`). So hitting the ceiling mid-walk does not
stall the sync; it converts every remaining product into a new-product
contribution for things Codex already holds. That is precisely the failure
Codex's own comment at `api/views_products.py:141-144` blames for 919
duplicates, arriving from the other direction. Codex softens it — a
`new_product` whose `file_hash` it already knows is converted to `edit_product`
(`api/views_contributions.py:207-242`) — but only for hashes it already has.
The fix is not only backoff: **a swallowed identify error must never be read as
"Codex does not have this."** `should_contribute` needs to distinguish "no
match" from "could not ask".

## Finding 6 — Grimoire never learns a contribution's fate

Confirmed intent: **Grimoire content never overrides Codex content, and
submissions go to Codex's moderation queue.** Codex enforces both — but not
uniformly, and Grimoire tracks neither outcome.

**Override protection holds on every path.** `guard_changes` runs for
`GRIMOIRE` and `API` sources, and `approve_contribution`
(`catalog/contributions.py:534`) passes `source=contribution.source` when a
moderator approves, so the guard applies at approval time too — not just on
direct submission. Nothing a Grimoire sync sends can replace a curated Codex
value, whichever route it takes.

**The moderation queue is not universal.** `_can_edit_directly`
(`api/views_contributions.py:472`) bypasses it for:

- superusers and moderators
- a publisher representative editing that publisher's product
- for `new_product`, anyone who represents any publisher

⚠️ **This almost certainly includes Michael's own account.** A superuser's
Grimoire sync returns `status: "applied"`, not `"pending"` — it is applied
immediately (still guarded, so still non-overriding).

**Decided (2026-08-23): this bypass goes away.** The rule dates from when
there was one contributor; with several people contributing, an admin's
submissions should be processed like anyone else's. A Grimoire sync will
queue regardless of privilege. That is a Codex-side change, planned in
`codex/docs/GRIMOIRE_MODERATION_PARITY_PLAN.md`.

⚠️ **An earlier draft of that gate keyed on the `source` label Grimoire itself
sends** — and that was the wrong place to put it. `_effective_source` maps a
token client to `API` unless it declares `grimoire`, and leaving `API` on
direct apply for the bulk importer's sake would have made `API` the *more*
privileged label: dropping one line from Grimoire's payload
(`services/codex.py:347`) would silently restore the bypass for a privileged
account. That inverts `_effective_source`'s own stated invariant — "a caller
may always claim less trust, never more" — and it puts the correctness of a
Codex authorization rule in the hands of this client's payload, where a
routine Grimoire refactor could disarm it.

**Decided (2026-08-24): the Codex gate keys on authentication, not on the
label.** Any `HashedTokenAuthentication` request queues — a token client is a
machine whatever it calls itself — and `scripts/dtrpg_library.py` gets an
explicit exemption on its own token rather than inheriting one by saying less.
The change is Codex-side and is written into
`codex/docs/GRIMOIRE_MODERATION_PARITY_PLAN.md` Phase 1.

**What that means for this plan: nothing Grimoire does can turn the gate off.**
That is the point of the decision. Grimoire should still send
`"source": "grimoire"` on every request and should still have a test asserting
it — the label remains how a contribution is *attributed*, filtered
(`?source=grimoire`) and merge-guarded (`GUARDED_SOURCES`) — but it is no
longer what decides whether moderation applies. Keep the test; it now protects
attribution rather than authorization.

Two consequences land squarely on this plan:

- **Phase 2's polling becomes mandatory, not optional.** Once every sync
  queues, `warnings` never arrive inline — they are produced at approval and
  stored in `review_notes`. Polling becomes the only way Grimoire learns
  anything about a contribution's outcome.
- **`duplicate_pending` stops being an edge case.** It fires when a `PENDING`
  contribution already exists for a file hash. With one contributor that was
  rare; with several people owning the same books it is routine — and
  Grimoire currently records that 400 as a permanent failure (Finding 2).

**Grimoire Phase 2 should therefore land before the Codex parity change**,
or ordinary syncs will start failing visibly and products will become
permanently un-contributable. (Phase 3 is unrelated to parity and cannot
land that early — see the phase note below.)

⚠️ **But half of the Codex work has to come first.** The parity plan's Phase 1
is two changes: the `review_notes` fix (above) and the gate itself. Phase 2
here needs the first and must precede the second, so the real order is
**Codex `review_notes` fix → Grimoire Phase 2 → Codex gate**. Not circular,
but it means the Codex branch ships as two commits with this work in between,
and that is worth agreeing before either side starts.

**Grimoire never closes the loop.** `ContributionStatus.REJECTED` exists in
`models/contribution.py:16` and **nothing ever sets it**. Nothing re-reads a
submitted contribution. A contribution sits at `SUBMITTED` forever whether it
was approved, rejected, or largely held back.

That is not merely cosmetic, because `queue_product_for_contribution`
(`services/sync_service.py:467`) refuses to re-contribute a product whose
contribution is `PENDING` or `SUBMITTED`:

> **A rejected contribution permanently blocks that product from ever being
> contributed again.** Reject once on Codex, and Grimoire will decline to
> offer that product for the rest of the install's life, with no way to tell
> from the Grimoire side why.

**And on the queued path, `warnings` never reach Grimoire at all.** They are
generated when the apply runs — which for a queued contribution is at
approval, long after Grimoire's request returned `pending`. Codex stores them
in `contribution.review_notes`. So Finding 3's warnings only ever appear in
the response for the *direct-apply* path; for the moderated path they are
reachable only by reading the contribution back.

Both problems have the same fix: poll submitted contributions.

---

## Where the work happens

Michael's primary Grimoire install, and the real library, are on his **home
computer**; this laptop has a sample `pdfs/` folder and the Docker dev stack.
So each phase below is marked:

- **[dev]** — code, unit tests, recorded/synthetic fixtures. Either machine.
- **[home]** — needs the real library or a live Codex call to be believed.

A phase is not done when tests pass on the dev laptop; it is done when its
`[home]` step has been run. Phases are ordered so the `[home]` steps cluster,
rather than forcing a machine switch per phase.

## Phases

### Phase 0 — Confirm against the live API **[home]**

Before changing code. Against the deployed Codex, for one product known to be
in the catalogue:

- `GET /identify?hash=…` and record the raw JSON.
- `GET /identify?title=…` likewise.
- Run one `sync_product_from_codex` and capture the traceback (or absence).

The throttle needs no session to establish: it is `60/minute` per IP, read
straight from `codex/backend/apps/core/throttling.py:34`. See Finding 5.

Save the payloads into `backend/tests/fixtures/codex/` as the fixtures every
later phase tests against. This is the step that turns Finding 1 from
"the serializer says so" into a fact, and it costs one session at the home
machine.

### Phase 1 — Fix the read path **[dev]**, verify **[home]**

- `CodexProduct.from_dict` accepts nested `publisher` / `game_system`
  (object *or* string, so an older deployment keeps working), derives
  `publication_year` from `publication_date`, reads `dtrpg_id` and `links`,
  and pulls `author` from `credits`.
- `sync_product_from_codex` never assigns a non-scalar to a scalar column —
  a type guard in the mapping loop, as a backstop so a future Codex reshape
  degrades instead of raising. This is *in addition to* the `from_dict` fix
  above, not instead of it: the guard protects one call site and `from_dict`
  protects all of them.
- **`check_for_updates` gets a regression test of its own**
  (`services/sync_service.py:344`). It reads the same fields through a separate
  mapping list at `:368` and reports differences rather than writing them, so
  the type guard above never runs there. Assert that a product matching a Codex
  record with a nested `publisher` reports *no* difference on that field —
  which is the behaviour `from_dict` restores, and the thing that silently
  breaks if someone later "simplifies" the fix down to the guard.
- **`sync_all_products` rolls back before continuing.** Its per-product
  `except` (`services/sync_service.py:329-331`) currently leaves the session
  inactive after a failed commit, so one bad row fails every row after it.
  `await db.rollback()` in the handler, and a test that a product which raises
  on commit does not prevent the next one syncing.
- Regression test per field in the table above, driven by the Phase 0 fixtures.

### Phase 2 — Honest contribution outcomes **[dev]**

- New `ContributionStatus` values distinguishing `no_change` and
  `duplicate_pending` from real failure; neither should be retried forever.
- Persist `existing_product_id` / `existing_contribution_id` rather than
  discarding them.
- Surface `warnings` on the contribution record and in the UI.
- **Authenticate `/identify`** — add the `Authorization: Token` header to
  `identify_by_hash` and `identify_by_title` (`services/codex.py:257`, `:294`),
  per the decision in Finding 5. This removes the 60/minute ceiling rather than
  working around it.
- **Pace the library walk, and keep 429 handling as a backstop.** A shared
  delay across `sync_all_products` and `submit_all_pending` rather than a
  per-product one, since the bucket was per IP. With the header above the
  throttle should never fire; handle it anyway, because "should never fire" is
  what the swallowed-error bug below was also assumed to be. A 429 that *does*
  arrive means an assumption broke and must be loud, not retried silently
  forever.
- **Distinguish "Codex has no match" from "Codex could not be asked."**
  `identify_by_hash` / `identify_by_title` currently return `None` for both,
  and `should_contribute` reads `None` as `new_product` — so a throttle, a
  timeout or a 500 all produce a duplicate contribution (Finding 5). Return a
  third state, or raise, and have `should_contribute` skip rather than
  contribute when the lookup failed.
- **Store the handle polling needs.** `ContributionQueue` has
  `codex_product_id` — which nothing ever writes — and **no column at all for
  Codex's contribution id**. `submit_contribution`
  (`services/contribution_service.py:153`) logs `result.contribution_id` and
  discards it. Polling is impossible until a migration adds
  `codex_contribution_id`. This is a schema change and should be the first
  commit of the phase.
  - **`codex_product_id` has fewer sources than it looks.** The intention was
    to fill it from an `applied` response and from `existing_product_id` on a
    `no_change`. Once the Codex parity change lands there is no `applied`
    response for a Grimoire sync — the queued path returns `201` with
    `contribution_id` and no `product_id`
    (Codex `api/views_contributions.py:356`), and for a `new_product` the
    Codex `Product` does not exist until a moderator approves. So after parity
    the only sources are `no_change` and polling. Write it that way now rather
    than shipping a branch that goes dead on the parity merge.
- **Poll submitted contributions** (`GET /contributions/?…`) to resolve
  `SUBMITTED`, read `review_notes` for the held-back warnings the queued path
  never returns inline, and unblock re-contribution once a contribution is no
  longer outstanding. Fixes the permanent-block bug in Finding 6.
  - **The read side on Codex is ready; the write side is not.**
    `ContributionSerializer` carries `status` and `review_notes`, a
    non-moderator's list is filtered to their own rows, and `filterset_fields`
    covers `status` and `source`. But both Codex review paths assign the
    moderator's `review_notes` over the apply warnings before saving
    (Finding 3), so **the warnings half of this bullet cannot work until the
    Codex-side fix in `GRIMOIRE_MODERATION_PARITY_PLAN.md` Phase 1 lands.**
    The status half works today. Build the poller so the warnings are a field
    it reads if present, not a thing it assumes.
  - **Status vocabulary.** Codex's states are `pending` / `approved` /
    `rejected` (`catalog/models/catalog.py:665`); Grimoire's enum has
    `ACCEPTED`, not `APPROVED` (`models/contribution.py:16`). Map Codex
    `approved` → local `ACCEPTED`; do not add a fourth spelling.
  - **Unblocking must not become a resubmit loop.** `queue_product_for_contribution`
    blocks only on `PENDING` / `SUBMITTED` (`services/sync_service.py:510`), so
    the moment polling writes `REJECTED` the next sync re-queues the identical
    payload, Codex re-rejects it, and this repeats every sync forever — and
    each round leaves another rejected row in the moderation queue. A rejected
    contribution must therefore stay un-resent **until the local data changes**:
    record the payload (or its hash) alongside the rejection and refuse to
    re-queue an unchanged one. Codex's own `duplicate_pending` cannot help
    here, because a rejected contribution is no longer `PENDING`.

### Phase 3 — Codex eligibility guard **[dev]**

The `is_codex_eligible` predicate from the multi-format plan, wired into both
call sites (`should_contribute` and `queue_contribution`) and returning
`(bool, reason)`. Outbound only; reading from Codex stays enabled for
everything.

Note the signature mismatch at the second site: `queue_contribution`
(`services/contribution_service.py:99`) takes `product_id: int`, not a
`Product`, so it must load the row before it can ask. Either widen the
predicate to accept an id, or load once at the top of the function — but do
not push the check up to its callers, since being the one place they all pass
through (`sync_service.py:535`, `:600`, `api/routes/contributions.py:95`) is
the entire reason it is the backstop.

⚠️ **Do not put the predicate in `sync_service.py`, where the multi-format plan
drafts it.** `sync_service` already imports `contribution_service` at module
level (`sync_service.py:14`), and `contribution_service` imports nothing back —
so a `contribution_service.queue_contribution` that reaches for
`sync_service.is_codex_eligible` closes an import cycle. The codebase's habit
of working around that with a function-local import (`should_contribute` does
exactly this for `get_cover_image_base64`) is a bad home for a guard whose
whole job is to be unbypassable: a deferred import is one refactor away from
being deferred right past the call.

Put it in `contribution_service.py`, or in a small module of its own that both
import. Prefer the second — the predicate is about *what may be shared*, which
is neither service's subject, and a file named for that is harder to
accidentally dismantle than a helper sitting among sync internals.

⚠️ **Ships in two halves, and this phase is only the first.** The predicate as
drafted in the multi-format plan opens with `product.file_type != "pdf"`, and
`Product` **has no `file_type` column** — `models/product.py:100` has
`is_image_content` and nothing else of the sort. That column arrives in
multi-format Phase 2, so this phase cannot contain that clause without
depending on the work it is supposed to precede.

- **Here (before multi-format):** the image/map half —
  `is_image_content` and `product_type in IMAGE_PRODUCT_TYPES`. That is the
  pre-existing bug on its own merits: a stock-art PDF with a title is
  contributable today, which the classifier's own `Art/Maps` verdict says it
  should not be. `IMAGE_PRODUCT_TYPES` does not exist yet either and is
  defined here.
- **In multi-format Phase 2, with the column:** add the `file_type != "pdf"`
  clause and its test, in the same commit that adds `file_type`.

### Phase 4 — Close the drift **[dev]**, verify **[home]**

- Send `links` instead of / alongside the legacy `dtrpg_url` + `itch_url`.
- Add `dtrpg_id` to Grimoire's Product model and populate it from
  `dtrpg_import`; send it on contribution and use it as `/identify`'s first
  lookup, ahead of hash.
- Consider `game_systems` / `authors` / `genres` plurals.
- `ai_disclosure`: nothing to do — the key is deliberately never sent.
  (For reference: `is_absent` treats `""` as absent, so even an empty value
  would have been harmless — but omission is the honest spelling.)

### Phase 5 — First real sync **[home]**

Run enrichment across the real library, with the throttle handling in place.
**Do not run this before Phase 2's throttle work**, whichever form Finding 5's
decision gives it: without it, hitting the ceiling mid-walk silently converts
the rest of the library into duplicate `new_product` contributions rather than
stopping.
Record how many products matched, how many were enriched, how many hit
`no_change`, and whether the rate limit was reached. This is the acceptance
test for Phases 1–4 and cannot be simulated on the dev laptop.

⚠️ If the Codex parity change (`GRIMOIRE_MODERATION_PARITY_PLAN.md`) has not
yet landed, run the contribution half **twice**: once from the admin account
(direct-apply branch) and once from an ordinary Codex account (moderation
queue). Only the second is what a real Grimoire user experiences. Once parity
lands, there is one path and the admin account exercises it like any other.

## Sequencing against multi-format scanning

Phase 3 here **owns** the Codex-eligibility predicate; the multi-format plan
references it rather than restating it. The dependency is not one-way: Phase 3
ships the image/map half, and multi-format Phase 2 completes it with the
`file_type` clause once that column exists (see the phase note above). Phases
0–2 should land before multi-format Phase 1 — not because they conflict, but
because debugging a broken read path is much harder once a second variable
(new file types) is in the library. Phase 4 can run in parallel with
multi-format work; Phase 5 wants to be a single deliberate session at the home
machine.

## Open questions

1. *(resolved)* **`ai_disclosure` is never sent.** It declares whether the
   *product's content* was AI generated — a fact about the published work,
   not about Grimoire's use of AI to identify or extract metadata. Grimoire
   cannot know it from scanning a file, so it does not guess: the key is
   omitted entirely and Codex's default (`""`, "not declared") stands. An
   omitted key means "leave it alone" throughout the apply path, so this is
   also the only spelling that cannot disturb a declaration made on Codex.
   If it is ever wanted, it must arrive as a field the user sets themselves,
   never as anything inferred.
2. **`credits` → `author`.** Codex models credits as structured roles.
   Flattening them into Grimoire's single `author` string loses the role.
   Take the first credit, join them, or add a Grimoire-side credits table?
3. **Is the deployed Codex actually current with `main`?** Phase 0 answers
   this, and if the deployment is behind, Phase 1's compatibility shims are
   load-bearing rather than defensive.
