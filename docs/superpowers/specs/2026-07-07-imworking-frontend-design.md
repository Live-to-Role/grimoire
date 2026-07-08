# "I'm Working" Mode — Frontend Design

**Date:** 2026-07-07
**Status:** Design approved, pending spec review
**Parent spec:** `docs/superpowers/specs/2026-07-07-worker-consolidation-design.md` (sections 4–6)

## Context

The worker-consolidation backend work (merged to `main`, HEAD `a77ab64`) moved all
heavy `ProcessingQueue` draining into a dedicated `grimoire.worker.run` process and
made pause **DB-backed and cross-process** via a `Setting` row `processing_paused`
(default `true` = the app starts paused, "I'm working" mode). It also **removed** the
inline `POST /queue/process` and `POST /queue/{id}/process` endpoints.

Consequence: the frontend "Process Batch Now" button in `LibraryManagement.tsx`
(`processQueueMutation`, calling `POST /queue/process`) now 404s. And there is no UI
to toggle the new pause mode or to nudge the user to enable processing after idle.

This spec covers the **frontend only**. The backend endpoints it relies on already
exist: `GET /queue/stats` (returns counts + `paused`), `POST /queue/pause`,
`POST /queue/resume`.

## Goals

- A prominent, always-visible **"I'm working" toggle** bound to the DB pause flag.
- Reflect live queue state (counts + paused) via **polling `GET /queue/stats`**
  (the out-of-process worker's events do not reach the API's SSE clients).
- A **30-minute idle prompt** nudging the user to start background processing.
- Fix the 404: replace "Process Batch Now" with a **Resume** control.

## Non-Goals

- Cross-process live SSE progress bridge (documented follow-up in the parent spec).
- Auto-resume on idle — we prompt, we do not auto-start.
- Any backend change. All required endpoints already exist.
- Adding a frontend test framework if none exists (see Testing).

## Current Frontend Architecture (as found)

- **Routing:** state-based via `activeView` in `App.tsx` (no react-router). Each page
  renders its own header; there is **no global top bar**.
- **Chrome:** `NavRail` (72px left icon rail, desktop) + `NavBottomBar` (fixed bottom,
  mobile). `NavRail`/`NavBottomBar` already accept an unused `queueCount` badge prop.
- **Queue UI:** `components/ProcessingQueue.tsx` is a full view; it already polls
  `GET /queue/stats` (`queryKey ['queue-stats']`, 30s) and *also* uses the now-dead
  `hooks/useQueueEvents.ts` SSE hook (the only importer of it).
- **Theming:** CSS variables (`var(--color-*)`), per the NavRail pattern.

## Design

### 1. Shared status hook — `hooks/useQueueStatus.ts` (new)

React Query on the existing key `['queue-stats']`, `queryFn` → `GET /queue/stats`,
`refetchInterval: 5000`. Returns `{ paused, pending, processing, completed, failed,
total, pending_by_type }`. Single source of truth for the widget, the
Library-Management card, and the idle logic. Reuses the `['queue-stats']` key so the
existing `ProcessingQueue.tsx` query dedupes with it. Add `paused: boolean` to the
shared `QueueStats` type.

### 2. Floating widget — `components/ProcessingStatusWidget.tsx` (new)

Rendered once in `App.tsx`, fixed **bottom-right**, offset above the mobile
`NavBottomBar` (e.g. `bottom-16` under `lg`, `bottom-4` at `lg+`). Shows a pause/play
state icon, an "I'm working" label, a live count (`N queued` / `N processing`), and a
switch bound to `paused`:

- Switch **ON = paused** ("I'm working") → `POST /queue/pause`
- Switch **OFF = running** → `POST /queue/resume`

Pause/resume mutations optimistically update the `['queue-stats']` cache (instant
switch feel) and invalidate on settle. CSS-variable theming.

### 3. Idle prompt — integrated into the widget

New `hooks/useIdleTimer.ts` tracks genuine activity: `mousemove`, `keydown`, `click`,
`visibilitychange`. Named constant `IDLE_PROMPT_MINUTES = 30`. Exposes an `isIdle`
flag that flips `true` after the threshold and resets on any tracked activity.

The widget expands to show the prompt when **`isIdle && paused && !dismissed`**:
> "You've been idle — start background processing?"  **[Start]**  **[Dismiss]**

- **Start** → `resume()` + reset timer.
- **Dismiss** → hide until another full idle interval elapses (dismissed state clears
  when activity resets the timer).
- Never shown while already running (not paused).

Folding the prompt into the widget keeps all processing controls in one place instead
of adding a second floating element.

### 4. Library-Management "Process Batch Now" → Resume

In `pages/LibraryManagement.tsx`, remove `processQueueMutation` (the 404'd
`POST /queue/process`). The Queue-Active card becomes context-aware using the shared
`paused`:

- **Paused** → a **[▶ Resume]** button calling `POST /queue/resume`.
- **Running** → the existing background-processing indicator, no button.

### 5. SSE cleanup

Remove the `useQueueEvents()` call from `ProcessingQueue.tsx` and delete
`hooks/useQueueEvents.ts` (only that one file imports it). Polling via
`useQueueStatus` now drives updates. The `/queue/events` endpoint stays server-side
(harmless), per the parent spec.

### 6. NavRail queue badge

Feed the existing unused `queueCount` prop on `NavRail`/`NavBottomBar` with
`pending + processing` from the shared hook at the `App.tsx` level (the hook is
already mounted there for the widget).

## Data Flow

`useQueueStatus` polls every 5s → provides `paused` + counts to the widget,
the Library-Management card, `ProcessingQueue`, and the NavRail badge. Toggle/resume
mutations `POST /queue/pause|resume` → optimistic cache update + invalidate
`['queue-stats']` → UI reflects immediately, corrected on the next poll.

## Testing

Component tests **only if** the frontend already has a test harness — the repo's
documented test infrastructure is backend-only (pytest). During planning, verify
whether `frontend/package.json` includes vitest / React Testing Library.

- **If a harness exists:** (a) idle timer fires the prompt after the threshold and
  **Start** calls resume (fake timers); (b) the widget reflects `paused` and its
  toggle calls pause/resume.
- **If no harness exists:** flag it and fall back to manual verification (do not add a
  test framework unprompted). Manual: toggle flips the flag (confirm via
  `GET /queue/stats`); Resume drains the queue; the idle prompt appears after the
  threshold (temporarily lowered for the check) and Start resumes.

## Files Touched (anticipated)

- **New:** `frontend/src/hooks/useQueueStatus.ts`
- **New:** `frontend/src/hooks/useIdleTimer.ts`
- **New:** `frontend/src/components/ProcessingStatusWidget.tsx`
- `frontend/src/App.tsx` — mount the widget + shared hook; pass `queueCount` to nav
- `frontend/src/pages/LibraryManagement.tsx` — remove `processQueueMutation`; Resume card
- `frontend/src/components/ProcessingQueue.tsx` — drop `useQueueEvents`; share status type
- **Delete:** `frontend/src/hooks/useQueueEvents.ts`

## Out of Scope / Follow-ups

- Cross-process live SSE progress bridge.
- Auto-resume (vs. prompt) on idle, as an optional setting.
- Single-process model load for query embedding (Pi/low-RAM), from the parent spec.
