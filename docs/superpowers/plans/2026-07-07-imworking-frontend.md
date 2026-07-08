# "I'm Working" Mode — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the frontend UI for the DB-backed "I'm working" pause mode — a global floating toggle + queue status widget, a 30-minute idle prompt, a Resume control replacing the 404'd "Process Batch Now" button, and removal of the now-dead SSE hook.

**Architecture:** A shared React Query hook (`useQueueStatus`) polls `GET /queue/stats` every 5s and is the single source of truth for `paused` + queue counts. A global `ProcessingStatusWidget` (mounted in `App.tsx`, inside the QueryClientProvider) renders the toggle, live counts, and the idle prompt. Pause/resume go through `useProcessingControls` (optimistic). Activity tracking lives in `useIdleTimer`.

**Tech Stack:** React 19, TypeScript (strict, `verbatimModuleSyntax`), `@tanstack/react-query` v5, lucide-react, Tailwind v4 + CSS variables. Vite build.

**Spec:** `docs/superpowers/specs/2026-07-07-imworking-frontend-design.md`

**Branch:** `feat/imworking-frontend` (already checked out, based on current `main`).

---

## Environment & Conventions (read first)

- **All commands run from `frontend/`** (`C:\Users\mkemi\Projects\grimoire\frontend`). On Windows use the Bash tool for git; run npm/npx via the Bash or PowerShell tool.
- **No test framework exists.** Do NOT add one. Verification per task = TypeScript build check + (final) lint + manual notes.
- **Verification command:** `npx tsc -b`
  - **Baseline (pre-existing, NOT yours to fix):** exactly one error is expected on every run —
    `src/pages/Settings.tsx(3,137): error TS6133: 'Shield' is declared but its value is never read.`
  - **A task passes** when `npx tsc -b` reports **no errors in the files you created/modified** — i.e. the *only* remaining error is that one pre-existing `Settings.tsx` line. If your changed files produce any error, fix them before committing.
- **TypeScript strictness that will bite you:**
  - `verbatimModuleSyntax: true` → import types with `import type { X }`, values with `import { y }`. Never mix a type into a value import.
  - `noUnusedLocals` / `noUnusedParameters` → no unused imports, variables, or destructured props. Prefix intentionally-unused params with `_`.
- **API client:** `frontend/src/api/client.ts` has a **default export** (used elsewhere as `import apiClient from '../api/client'`). All endpoints are relative to the client's base (`/queue/stats`, not `/api/v1/queue/stats`).
- **Theming:** inline `style={{ ... 'var(--color-*)' }}`, matching `NavRail.tsx` / `ProcessingQueue.tsx`. Do NOT introduce hard-coded palette Tailwind classes for surfaces/borders (the blue accents in the Library card are an existing exception you may match).
- **Only touch the files each task names.** Leave unrelated working-tree changes and untracked files alone. Use precise `git add <path>` (never `git add -A`).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `frontend/src/hooks/useQueueStatus.ts` | Poll `/queue/stats`; export shared `QueueStats` type | **Create** |
| `frontend/src/hooks/useProcessingControls.ts` | Pause/resume mutations (optimistic) | **Create** |
| `frontend/src/hooks/useIdleTimer.ts` | Activity tracking + idle threshold | **Create** |
| `frontend/src/components/ProcessingStatusWidget.tsx` | Global floating toggle + counts + idle prompt | **Create** |
| `frontend/src/App.tsx` | Mount the widget inside the providers | Modify |
| `frontend/src/components/NavRail.tsx` | Queue badge from shared hook (self-fetch) | Modify |
| `frontend/src/pages/LibraryManagement.tsx` | Remove `processQueueMutation`; Resume card | Modify |
| `frontend/src/components/ProcessingQueue.tsx` | Drop SSE hook; use shared `QueueStats` type | Modify |
| `frontend/src/hooks/useQueueEvents.ts` | Dead SSE hook | **Delete** |

---

## Task 1: Shared `useQueueStatus` hook + `QueueStats` type

**Files:**
- Create: `frontend/src/hooks/useQueueStatus.ts`

- [ ] **Step 1: Create the hook**

Create `frontend/src/hooks/useQueueStatus.ts`:

```ts
import { useQuery } from '@tanstack/react-query';
import apiClient from '../api/client';

export interface QueueStats {
  pending: number;
  processing: number;
  completed: number;
  failed: number;
  total: number;
  pending_by_type?: Record<string, number>;
  paused: boolean;
}

/**
 * Single source of truth for queue status. Polls GET /queue/stats every 5s.
 * Shares the ['queue-stats'] query key so all consumers dedupe to one request.
 */
export function useQueueStatus() {
  return useQuery<QueueStats>({
    queryKey: ['queue-stats'],
    queryFn: async () => {
      const res = await apiClient.get<QueueStats>('/queue/stats');
      return res.data;
    },
    refetchInterval: 5000,
  });
}
```

- [ ] **Step 2: Verify the build**

Run (from `frontend/`): `npx tsc -b`
Expected: no errors in `src/hooks/useQueueStatus.ts` (only the pre-existing `Settings.tsx` `Shield` error may appear). An unused *export* is fine — `noUnusedLocals` does not flag exported members.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useQueueStatus.ts
git commit -m "feat(frontend): shared useQueueStatus hook polling /queue/stats"
```

---

## Task 2: `useProcessingControls` hook (pause/resume, optimistic)

**Files:**
- Create: `frontend/src/hooks/useProcessingControls.ts`

- [ ] **Step 1: Create the hook**

Create `frontend/src/hooks/useProcessingControls.ts`:

```ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import apiClient from '../api/client';
import type { QueueStats } from './useQueueStatus';

interface OptimisticContext {
  prev?: QueueStats;
}

/**
 * Pause = enable "I'm working" (POST /queue/pause).
 * Resume = disable it (POST /queue/resume).
 * Both optimistically flip `paused` in the ['queue-stats'] cache so the toggle
 * feels instant, roll back on error, and re-sync on settle.
 */
export function useProcessingControls() {
  const queryClient = useQueryClient();

  const buildOptions = (endpoint: string, nextPaused: boolean) => ({
    mutationFn: async () => {
      await apiClient.post(endpoint);
    },
    onMutate: async (): Promise<OptimisticContext> => {
      await queryClient.cancelQueries({ queryKey: ['queue-stats'] });
      const prev = queryClient.getQueryData<QueueStats>(['queue-stats']);
      if (prev) {
        queryClient.setQueryData<QueueStats>(['queue-stats'], { ...prev, paused: nextPaused });
      }
      return { prev };
    },
    onError: (_err: Error, _vars: void, context: OptimisticContext | undefined) => {
      if (context?.prev) {
        queryClient.setQueryData(['queue-stats'], context.prev);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
    },
  });

  const pause = useMutation<void, Error, void, OptimisticContext>(
    buildOptions('/queue/pause', true),
  );
  const resume = useMutation<void, Error, void, OptimisticContext>(
    buildOptions('/queue/resume', false),
  );

  return { pause, resume };
}
```

- [ ] **Step 2: Verify the build**

Run: `npx tsc -b`
Expected: no errors in `src/hooks/useProcessingControls.ts` (only the pre-existing `Settings.tsx` error). If TS complains about the `buildOptions` spread inference, inline the two option objects directly into each `useMutation<void, Error, void, OptimisticContext>({ ... })` call instead — same fields, no shared helper.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useProcessingControls.ts
git commit -m "feat(frontend): useProcessingControls pause/resume mutations"
```

---

## Task 3: `useIdleTimer` hook

**Files:**
- Create: `frontend/src/hooks/useIdleTimer.ts`

- [ ] **Step 1: Create the hook**

Create `frontend/src/hooks/useIdleTimer.ts`:

```ts
import { useEffect, useRef, useState } from 'react';

export const IDLE_PROMPT_MINUTES = 30;

/**
 * Returns true after `idleMinutes` with no tracked activity
 * (mousemove / keydown / click / tab becoming visible again).
 * Any activity resets the timer and flips the result back to false.
 */
export function useIdleTimer(idleMinutes: number = IDLE_PROMPT_MINUTES): boolean {
  const [isIdle, setIsIdle] = useState(false);
  const timerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const idleMs = idleMinutes * 60 * 1000;

    const reset = () => {
      setIsIdle(false);
      if (timerRef.current !== undefined) {
        window.clearTimeout(timerRef.current);
      }
      timerRef.current = window.setTimeout(() => setIsIdle(true), idleMs);
    };

    const events: (keyof WindowEventMap)[] = ['mousemove', 'keydown', 'click'];
    events.forEach((e) => window.addEventListener(e, reset, { passive: true }));

    const onVisibility = () => {
      if (document.visibilityState === 'visible') reset();
    };
    document.addEventListener('visibilitychange', onVisibility);

    reset(); // start the countdown

    return () => {
      events.forEach((e) => window.removeEventListener(e, reset));
      document.removeEventListener('visibilitychange', onVisibility);
      if (timerRef.current !== undefined) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, [idleMinutes]);

  return isIdle;
}
```

- [ ] **Step 2: Verify the build**

Run: `npx tsc -b`
Expected: no errors in `src/hooks/useIdleTimer.ts` (only the pre-existing `Settings.tsx` error).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useIdleTimer.ts
git commit -m "feat(frontend): useIdleTimer activity/idle detection hook"
```

---

## Task 4: `ProcessingStatusWidget` component

**Files:**
- Create: `frontend/src/components/ProcessingStatusWidget.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/ProcessingStatusWidget.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Loader2, Pause, Play } from 'lucide-react';
import { useQueueStatus } from '../hooks/useQueueStatus';
import { useProcessingControls } from '../hooks/useProcessingControls';
import { useIdleTimer } from '../hooks/useIdleTimer';

/**
 * Global, always-visible processing status + "I'm working" toggle.
 * Rendered once in App.tsx (inside the QueryClientProvider). Fixed bottom-right,
 * offset above the mobile bottom nav. Expands to show an idle prompt after the
 * idle threshold when processing is paused.
 */
export function ProcessingStatusWidget() {
  const { data: status } = useQueueStatus();
  const { pause, resume } = useProcessingControls();
  const isIdle = useIdleTimer();
  const [dismissed, setDismissed] = useState(false);

  // Once the user is active again, allow the prompt to appear on the next idle.
  useEffect(() => {
    if (!isIdle) setDismissed(false);
  }, [isIdle]);

  if (!status) return null;

  const paused = status.paused;
  const showPrompt = isIdle && paused && !dismissed;

  const onToggle = () => {
    if (paused) {
      resume.mutate();
    } else {
      pause.mutate();
    }
  };

  const detail = paused
    ? `${status.pending} queued`
    : `${status.processing} processing · ${status.pending} queued`;

  return (
    <div
      className="fixed right-4 bottom-16 lg:bottom-4 z-40 w-64 rounded-xl border shadow-lg"
      style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
    >
      {showPrompt && (
        <div className="border-b p-3" style={{ borderColor: 'var(--color-border)' }}>
          <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
            You&apos;ve been idle — start background processing?
          </p>
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => {
                resume.mutate();
                setDismissed(true);
              }}
              className="rounded-md px-3 py-1.5 text-sm font-medium text-white"
              style={{ backgroundColor: 'var(--color-accent)' }}
            >
              Start
            </button>
            <button
              onClick={() => setDismissed(true)}
              className="rounded-md border px-3 py-1.5 text-sm font-medium"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      <div className="flex items-center gap-3 p-3">
        {paused ? (
          <Pause className="h-5 w-5" style={{ color: 'var(--color-text-secondary)' }} />
        ) : status.processing > 0 ? (
          <Loader2 className="h-5 w-5 animate-spin" style={{ color: 'var(--color-accent)' }} />
        ) : (
          <Play className="h-5 w-5" style={{ color: 'var(--color-accent)' }} />
        )}

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
            {paused ? "I'm working" : 'Processing'}
          </p>
          <p className="truncate text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {detail}
          </p>
        </div>

        <button
          role="switch"
          aria-checked={paused}
          aria-label='Toggle "I&apos;m working" mode'
          onClick={onToggle}
          disabled={pause.isPending || resume.isPending}
          className="relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50"
          style={{ backgroundColor: paused ? 'var(--color-accent)' : 'var(--color-border)' }}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
              paused ? 'left-5' : 'left-0.5'
            }`}
          />
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the build**

Run: `npx tsc -b`
Expected: no errors in `src/components/ProcessingStatusWidget.tsx` (only the pre-existing `Settings.tsx` error). Confirm you did NOT import `IDLE_PROMPT_MINUTES` here (unused → would fail `noUnusedLocals`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ProcessingStatusWidget.tsx
git commit -m "feat(frontend): ProcessingStatusWidget toggle + idle prompt"
```

---

## Task 5: Mount the widget in `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add the import**

In `frontend/src/App.tsx`, find:

```tsx
import { ProcessingQueue } from './components/ProcessingQueue';
```

Add immediately after it:

```tsx
import { ProcessingStatusWidget } from './components/ProcessingStatusWidget';
```

- [ ] **Step 2: Render the widget inside the providers**

In `frontend/src/App.tsx`, find:

```tsx
          <NavBottomBar activeView={activeView} onViewChange={setActiveView} />
          <FilterDrawer
```

Insert the widget between them so it becomes:

```tsx
          <NavBottomBar activeView={activeView} onViewChange={setActiveView} />
          <ProcessingStatusWidget />
          <FilterDrawer
```

(The widget must live inside `<QueryClientProvider>`; this location is. Do NOT call `useQueueStatus` in the `App` function body — that runs outside the provider and throws.)

- [ ] **Step 3: Verify the build**

Run: `npx tsc -b`
Expected: no errors in `src/App.tsx` (only the pre-existing `Settings.tsx` error).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(frontend): mount ProcessingStatusWidget globally"
```

---

## Task 6: NavRail queue badge from the shared hook

The `queueCount` prop on `NavRail`/`NavBottomBar` is never passed by `App` (badge never shows). Since both components render inside the provider, have them self-fetch the count.

**Files:**
- Modify: `frontend/src/components/NavRail.tsx`

- [ ] **Step 1: Import the hook**

In `frontend/src/components/NavRail.tsx`, find:

```tsx
import { useThemeContext } from '../contexts/ThemeContext';
```

Add after it:

```tsx
import { useQueueStatus } from '../hooks/useQueueStatus';
```

- [ ] **Step 2: Remove the unused `queueCount` prop from the interface**

Find:

```tsx
interface NavRailProps {
  activeView: string;
  onViewChange: (view: string) => void;
  queueCount?: number;
}
```

Replace with:

```tsx
interface NavRailProps {
  activeView: string;
  onViewChange: (view: string) => void;
}
```

- [ ] **Step 3: `NavRail` — self-fetch the count**

Find:

```tsx
export function NavRail({ activeView, onViewChange, queueCount }: NavRailProps) {
  const { effectiveTheme, toggleTheme } = useThemeContext();
```

Replace with:

```tsx
export function NavRail({ activeView, onViewChange }: NavRailProps) {
  const { effectiveTheme, toggleTheme } = useThemeContext();
  const { data: queueStatus } = useQueueStatus();
  const queueCount = (queueStatus?.pending ?? 0) + (queueStatus?.processing ?? 0);
```

- [ ] **Step 4: `NavBottomBar` — self-fetch the count**

Find:

```tsx
export function NavBottomBar({ activeView, onViewChange, queueCount }: NavRailProps) {
  const { effectiveTheme, toggleTheme } = useThemeContext();
```

Replace with:

```tsx
export function NavBottomBar({ activeView, onViewChange }: NavRailProps) {
  const { effectiveTheme, toggleTheme } = useThemeContext();
  const { data: queueStatus } = useQueueStatus();
  const queueCount = (queueStatus?.pending ?? 0) + (queueStatus?.processing ?? 0);
```

(The existing `queueCount != null && queueCount > 0` badge render blocks in both components now read these locals. Since `queueCount` is always a number now, the `!= null` check stays harmless.)

- [ ] **Step 5: Verify the build**

Run: `npx tsc -b`
Expected: no errors in `src/components/NavRail.tsx` (only the pre-existing `Settings.tsx` error). Confirm no other file passed `queueCount` to these components (a search for `queueCount=` should find nothing — `App.tsx` never set it).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/NavRail.tsx
git commit -m "feat(frontend): NavRail queue badge from shared status hook"
```

---

## Task 7: LibraryManagement — remove `processQueueMutation`, add Resume card

**Files:**
- Modify: `frontend/src/pages/LibraryManagement.tsx`

- [ ] **Step 1: Add the imports**

In `frontend/src/pages/LibraryManagement.tsx`, find the `lucide-react` import block and its `Play,` line:

```tsx
  Play,
```

Add a `Pause,` line immediately before it (keep alphabetical-ish order like the file):

```tsx
  Pause,
  Play,
```

Then find:

```tsx
import apiClient from '../api/client';
```

Add after it:

```tsx
import { useQueueStatus } from '../hooks/useQueueStatus';
import { useProcessingControls } from '../hooks/useProcessingControls';
```

- [ ] **Step 2: Remove the 404'd mutation**

Find and DELETE this entire block:

```tsx
  const processQueueMutation = useMutation({
    mutationFn: async (maxItems: number) => {
      const res = await apiClient.post('/queue/process', {}, {
        params: { max_items: maxItems },
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['text-extraction-stats'] });
      queryClient.invalidateQueries({ queryKey: ['library-management-stats'] });
    },
  });
```

- [ ] **Step 3: Add the shared status + resume control**

Find (the first query in the component):

```tsx
  const { data: stats } = useQuery({
    queryKey: ['library-management-stats'],
```

Insert immediately BEFORE that line:

```tsx
  const { data: queueStatus } = useQueueStatus();
  const { resume } = useProcessingControls();

```

- [ ] **Step 4: Replace the "Queue Active" card**

Find and replace this entire block:

```tsx
            {/* Queue Status */}
            {extractionStats && (extractionStats.queue_pending > 0 || extractionStats.queue_processing > 0) && (
              <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
                    <div>
                      <p className="font-medium text-blue-900">
                        Queue Active: {extractionStats.queue_pending} pending, {extractionStats.queue_processing} processing
                      </p>
                      <p className="text-sm text-blue-700">
                        Processing in background. Stats refresh every 10 seconds.
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => processQueueMutation.mutate(appSettings?.extraction_batch_size || 100)}
                    disabled={processQueueMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 text-base font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    style={{ minHeight: '44px' }}
                  >
                    {processQueueMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="h-4 w-4" />
                    )}
                    Process Batch Now
                  </button>
                </div>
              </div>
            )}
```

with:

```tsx
            {/* Queue Status */}
            {extractionStats && (extractionStats.queue_pending > 0 || extractionStats.queue_processing > 0) && (
              <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {queueStatus?.paused ? (
                      <Pause className="h-5 w-5 text-blue-600" />
                    ) : (
                      <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
                    )}
                    <div>
                      <p className="font-medium text-blue-900">
                        Queue: {extractionStats.queue_pending} pending, {extractionStats.queue_processing} processing
                      </p>
                      <p className="text-sm text-blue-700">
                        {queueStatus?.paused
                          ? 'Background processing is paused ("I\'m working"). Resume to start.'
                          : 'Processing in the background.'}
                      </p>
                    </div>
                  </div>
                  {queueStatus?.paused && (
                    <button
                      onClick={() => resume.mutate()}
                      disabled={resume.isPending}
                      className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 text-base font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                      style={{ minHeight: '44px' }}
                    >
                      {resume.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Play className="h-4 w-4" />
                      )}
                      Resume
                    </button>
                  )}
                </div>
              </div>
            )}
```

- [ ] **Step 5: Verify the build**

Run: `npx tsc -b`
Expected: no errors in `src/pages/LibraryManagement.tsx` (only the pre-existing `Settings.tsx` error). If TS reports `Play` or `Loader2` unused, you removed their last other use — recheck; both are still used by this card. `Pause` is now used by this card.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/LibraryManagement.tsx
git commit -m "fix(frontend): replace removed /queue/process button with Resume"
```

---

## Task 8: Remove the dead SSE hook

`useQueueEvents` subscribes to `/queue/events`, but the out-of-process worker's events never reach the API's SSE clients. Polling now drives updates. Remove the hook and switch `ProcessingQueue` to the shared `QueueStats` type.

**Files:**
- Modify: `frontend/src/components/ProcessingQueue.tsx`
- Delete: `frontend/src/hooks/useQueueEvents.ts`

- [ ] **Step 1: Drop the SSE import and call in `ProcessingQueue.tsx`**

In `frontend/src/components/ProcessingQueue.tsx`, find and DELETE this import line:

```tsx
import { useQueueEvents } from '../hooks/useQueueEvents';
```

Then find and DELETE these two lines (the comment + call):

```tsx
  // SSE connection for real-time updates (falls back to polling below)
  useQueueEvents();
```

- [ ] **Step 2: Use the shared `QueueStats` type**

In `frontend/src/components/ProcessingQueue.tsx`, find and DELETE the local interface:

```tsx
interface QueueStats {
  pending: number;
  processing: number;
  completed: number;
  failed: number;
  total: number;
  pending_by_type?: Record<string, number>;
}
```

Then find the existing api-client import:

```tsx
import api from '../api/client';
```

Add after it:

```tsx
import type { QueueStats } from '../hooks/useQueueStatus';
```

(The component's `useQuery<QueueStats>` and `stats` usages now reference the shared type, which additionally has `paused` — no other change needed. The `/queue/stats` response already includes `paused`.)

- [ ] **Step 3: Delete the dead hook file**

```bash
git rm frontend/src/hooks/useQueueEvents.ts
```

- [ ] **Step 4: Verify the build + confirm no stragglers**

Run: `npx tsc -b`
Expected: no errors in `src/components/ProcessingQueue.tsx` (only the pre-existing `Settings.tsx` error).
Then search the repo for any remaining reference:
Run (from `frontend/`): `git grep -n "useQueueEvents" -- src` → expect **no matches**.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ProcessingQueue.tsx
git commit -m "refactor(frontend): drop dead queue SSE hook; poll for status"
```

---

## Task 9: Final verification

- [ ] **Step 1: Type-check the whole app**

Run (from `frontend/`): `npx tsc -b`
Expected: the **only** error is the pre-existing `src/pages/Settings.tsx(3,137): 'Shield' ... never read`. No errors in any file this plan created or modified.

- [ ] **Step 2: Lint the changed files**

Run: `npm run lint`
Expected: no **new** lint errors attributable to the new/modified files. (If the repo has pre-existing lint warnings elsewhere, note them but do not fix unrelated ones.)

- [ ] **Step 3: Manual end-to-end (requires the app running)**

Start the stack (backend API + the new queue worker + frontend) — e.g. `start.bat` on Windows — then, with no queue items paused by default (app starts paused):

1. **Widget visible + starts paused:** the floating widget shows bottom-right with the toggle ON ("I'm working"), pause icon, and `N queued`.
2. **Resume drains:** click the toggle OFF (or the Library Management → Processing → **Resume** button when items are pending). Confirm `GET /queue/stats` flips `"paused": false` and the worker begins processing (`processing` count rises; pending falls).
3. **Pause stops fetching:** toggle back ON → `"paused": true`; the worker stops fetching new items after the in-flight one finishes.
4. **NavRail badge:** with items pending/processing, the Queue nav item shows the count badge.
5. **Idle prompt (fast check):** temporarily set `IDLE_PROMPT_MINUTES = 0.1` in `useIdleTimer.ts`, reload while paused, stop touching the mouse/keyboard ~6s → the widget shows the idle prompt; **Start** flips to resumed; **Dismiss** hides it until the next idle interval. **Revert the constant to 30 afterward.**
6. **No SSE 404 noise:** the browser Network tab shows polling `GET /queue/stats` every ~5s and no `EventSource`/`/queue/events` connection.

- [ ] **Step 4: Confirm clean tree**

Run: `git status` → only the intended commits; no stray modifications to unrelated files.

---

## Notes for the executor

- If any `npx tsc -b` run surfaces an error in a file you did NOT touch **other than** the known `Settings.tsx` `Shield` line, stop and report it — do not fix unrelated files.
- The `Settings.tsx` `Shield` unused-import error is pre-existing and out of scope. Leave it.
- Frontend has no automated tests; the manual e2e in Task 9 is the behavioral gate. Report it as manual-pending if you cannot run the full stack in your environment.
