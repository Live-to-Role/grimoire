# Codex fixtures — Phase 0 capture

Recorded 2026-08-24 against the deployed Codex at
`https://codex-api.livetorole.com/api/v1`, on the home machine, against the
real 19,301-product library. Phase 0 of
`docs/plans/2026-08-23-codex-contract-realignment.md`.

| File | What it is |
|---|---|
| `identify_by_title.json` | `GET /identify?title=…`, `match: exact`, confidence 0.952. The payload Finding 1 is about. |
| `identify_by_hash_no_match.json` | `GET /identify?hash=…`, `match: none`. The **common** case — see below. |

## Confirmed

**Finding 1 is real, and the deployment is current with `main`.** That resolves
open question 3: the compatibility shims in Phase 1 are defensive, not
load-bearing. `/identify` returns `ProductDetailSerializer`, in which:

- `publisher` is an **object** — `{id, name, slug, logo_url, …}`
- `game_system` is an **object or `null`** (`SerializerMethodField` over the
  nominated primary link; `null` when none is nominated, even where
  `game_systems` is populated)
- `author`, `genre`, `publication_year`, `dtrpg_url`, `game_system_slug` are
  **absent**; the data lives in `credits`, `themes`/`tags`, `publication_date`,
  `dtrpg_id`/`links`, and inside `game_system`

**The trigger is common, not rare.** Of Grimoire's 37 queued contributions, 34
match Codex by title, and **20 of those return `publisher` as a dict**. Eight
also return `game_system` as a dict. Every one of those would bind a `dict` to
a `String(255)`.

**Finding 6, measured.** All 37 rows in `contribution_queue` are `SUBMITTED`,
and **0 of their 37 hashes are known to `/identify`**. Grimoire cannot tell
whether they are queued on Codex, rejected, or were never received.

## Found here, not in the plan

**1. `is_available()` runs per product, and `/health` throttles.**
`get_codex_client()` recreates its singleton whenever `api_key` is passed
(`codex.py:474` — `if _codex_client is None or refresh or api_key`), and
`sync_product_from_codex` always passes one. So `_available` never caches and
every product costs a `GET /health` *in addition to* its `/identify` call.

Once `/health` throttles, `is_available()` returns `False`, and
`sync_product_from_codex` returns `{"synced": False, "reason": "Codex
unavailable"}` for every remaining product. `sync_all_products` counts that as
**`skipped`, not `failed`** (`sync_service.py:325-327`), so a sync that
accomplished nothing reports a clean run. This would end Phase 5's first real
sync in its first minute, quietly.

**2. The throttle is wider and longer than the plan documents.** The plan
records `/identify` at 60/minute per IP. Observed: `/health` returned
`429 {"detail":"Request was throttled. Expected available in 3333 seconds."}`
— an hour-scale window — and `/products/{slug}/` throttled after roughly one
request. `/identify` itself was the most permissive endpoint tested.

**3. Hash lookup rarely matches, so the title fallback is the real path.**
Codex's 7,025 products come largely from a DriveThruRPG import and carry no
`file_hashes`. `sync_product_from_codex` tries hash first and falls back to
title (`sync_service.py:213-221`), so in practice it is the *title* branch that
returns the reshaped payload — which is what makes Finding 1 live rather than
latent. It also supports Finding 4's argument for `dtrpg_id` as the primary
lookup: the captured product has `dtrpg_id: "119267"` and a DriveThruRPG entry
in `links`.

**4. The deployment 403s a default `python-urllib` User-Agent.** `httpx` (what
Grimoire uses) and `curl` are fine. Worth knowing before writing a throwaway
diagnostic script and misreading the result as an outage.

**5. `/products/{id}/` 404s — the detail route keys on `slug`.**

## Not yet captured

`GET /identify?hash=…` **with a match**, and the live
`sync_product_from_codex` traceback. Both need a Codex product that carries a
file hash; the run was cut short by the hour-scale throttle above. The
`InterfaceError` is predicted rather than observed — treat it as such until
this is finished.
