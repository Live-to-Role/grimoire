# Codex Contract Realignment — Phased Plan

Status: draft for review
Date: 2026-08-23
Blocks: `2026-08-23-multi-format-scanning-design.md` (Codex eligibility work)

## Verdict

**Outbound contributions are still compatible. Inbound enrichment is broken.**

Every field Grimoire's `build_contribution_data` sends is in Codex's
`ALLOWED_PRODUCT_FIELDS`, and the envelope Grimoire's client posts
(`contribution_type`, `data`, `file_hash`, `source: "grimoire"`,
`Authorization: Token`) is exactly what `ContributionCreateSerializer`
expects. That path works and needs no emergency fix.

The read path does not. Codex's `/identify` now returns
`ProductDetailSerializer`, which **no longer has `author`, `genre`,
`publication_year`, `dtrpg_url` or `game_system_slug`**, and returns
`publisher` and `game_system` as **nested objects rather than strings**.
Grimoire's `CodexProduct.from_dict` (`services/codex.py:60`) still reads all
of those as flat values.

---

## Finding 1 — Codex enrichment writes a dict into a string column (severity: high)

`sync_product_from_codex` (`services/sync_service.py:228`) maps
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

On any product Codex actually matches, `publisher` and `game_system` bind a
`dict` to a VARCHAR parameter. Under aiosqlite that is an
`InterfaceError`, not a silent coercion — so enrichment does not degrade, it
raises, and it raises only for products Codex *does* know, which are the
ones the feature exists to serve.

Fields that silently became no-ops, because Codex no longer sends the key:

| Grimoire reads | Codex now sends |
|---|---|
| `author` | — (`credits`, a list of credit objects) |
| `genre` | — (`themes`, `tags`) |
| `publication_year` | `publication_date` (ISO string) |
| `dtrpg_url` | `dtrpg_id` + `links[]` |
| `game_system_slug` | inside the nested `game_system` object |

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

⚠️ **That gate keys on the `source` label Grimoire itself sends.**
`_effective_source` maps a token client to `API` unless it declares
`grimoire`, and the parity plan leaves `API` on direct apply for the bulk
importer's sake. So after parity, `API` is the *more* privileged label, and
dropping one line from the payload (`services/codex.py:347`) would silently
restore the bypass for a privileged account. Grimoire must keep sending
`"source": "grimoire"` on every request, and a test should assert it —
the correctness of the Codex-side rule now depends on this client's payload.

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

**Grimoire never closes the loop.** `ContributionStatus.REJECTED` exists in
`models/contribution.py:16` and **nothing ever sets it**. Nothing re-reads a
submitted contribution. A contribution sits at `SUBMITTED` forever whether it
was approved, rejected, or largely held back.

That is not merely cosmetic, because `queue_product_for_contribution`
(`services/sync_service.py:508`) refuses to re-contribute a product whose
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
  a type guard in the mapping loop, so a future Codex reshape degrades
  instead of raising.
- Regression test per field in the table above, driven by the Phase 0 fixtures.

### Phase 2 — Honest contribution outcomes **[dev]**

- New `ContributionStatus` values distinguishing `no_change` and
  `duplicate_pending` from real failure; neither should be retried forever.
- Persist `existing_product_id` / `existing_contribution_id` rather than
  discarding them.
- Surface `warnings` on the contribution record and in the UI.
- Handle 429 with backoff in `submit_all_pending` and `sync_all_products`.
  The bucket is per IP at 60/minute (Finding 5), so the backoff is shared
  across the whole library walk rather than per product.
- **Store the handle polling needs.** `ContributionQueue` has
  `codex_product_id` — which nothing ever writes — and **no column at all for
  Codex's contribution id**. `submit_contribution`
  (`services/contribution_service.py:150`) logs `result.contribution_id` and
  discards it. Polling is impossible until a migration adds
  `codex_contribution_id` (and the same write populates `codex_product_id`
  from an `applied` response and from `existing_product_id` on `no_change`).
  This is a schema change and should be the first commit of the phase.
- **Poll submitted contributions** (`GET /contributions/?…`) to resolve
  `SUBMITTED`, read `review_notes` for the held-back warnings the queued path
  never returns inline, and unblock re-contribution once a contribution is no
  longer outstanding. Fixes the permanent-block bug in Finding 6.
  - **Status vocabulary.** Codex's states are `pending` / `approved` /
    `rejected` (`catalog/models/catalog.py:665`); Grimoire's enum has
    `ACCEPTED`, not `APPROVED` (`models/contribution.py:16`). Map Codex
    `approved` → local `ACCEPTED`; do not add a fourth spelling.
  - **Unblocking must not become a resubmit loop.** `queue_product_for_contribution`
    blocks only on `PENDING` / `SUBMITTED` (`services/sync_service.py:509`), so
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
