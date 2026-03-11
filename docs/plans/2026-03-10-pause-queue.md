# Pause Queue Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow users to pause the processing queue from the bulk edit toolbar so product updates don't hit SQLite locking errors.

**Architecture:** Add a module-level `pause_event` (asyncio.Event) to the queue processor that the worker loop checks before fetching new batches. Expose pause/resume via two POST endpoints. Frontend adds a pause button to the floating toolbar and auto-resumes when the BulkEditModal closes.

**Tech Stack:** FastAPI (backend), React/TypeScript with React Query (frontend), existing queue worker architecture.

**Design doc:** `docs/plans/2026-03-10-bulk-update-design.md`

---

### Task 1: Add Pause/Resume to Queue Processor

**Files:**
- Modify: `backend/grimoire/services/queue_processor.py`

**Step 1: Add the pause event and accessor functions**

At the top of `queue_processor.py`, after the `TASK_HANDLERS = {}` line (line 18), add:

```python
# Pause control — set = running, clear = paused
_pause_event = asyncio.Event()
_pause_event.set()  # Start unpaused


def pause_queue():
    """Pause the queue worker (finishes in-flight tasks, stops fetching new ones)."""
    _pause_event.clear()


def resume_queue():
    """Resume the queue worker."""
    _pause_event.set()


def is_queue_paused() -> bool:
    """Check if the queue is currently paused."""
    return not _pause_event.is_set()
```

**Step 2: Add pause check to the worker loop**

In `run_queue_worker`, inside the `while True` loop (after the stop_event check at line 680), add a pause check:

```python
        # Wait if paused (check every second so we can still stop)
        while not _pause_event.is_set():
            if stop_event and stop_event.is_set():
                break
            await asyncio.sleep(1.0)
```

**Step 3: Commit**

```bash
git add backend/grimoire/services/queue_processor.py
git commit -m "feat: add pause/resume control to queue processor"
```

---

### Task 2: Add Pause/Resume API Endpoints

**Files:**
- Modify: `backend/grimoire/api/routes/queue.py`
- Test: `backend/tests/test_queue_pause.py` (create)

**Step 1: Write the test**

Create `backend/tests/test_queue_pause.py`:

```python
"""Tests for queue pause/resume."""
import pytest
from grimoire.services.queue_processor import pause_queue, resume_queue, is_queue_paused


@pytest.mark.asyncio
async def test_pause_and_resume():
    """Queue should toggle between paused and unpaused states."""
    # Starts unpaused
    assert not is_queue_paused()

    pause_queue()
    assert is_queue_paused()

    resume_queue()
    assert not is_queue_paused()


@pytest.mark.asyncio
async def test_resume_when_not_paused_is_noop():
    """Resuming when not paused should not error."""
    resume_queue()
    assert not is_queue_paused()
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_queue_pause.py -v`
Expected: FAIL — `pause_queue` not yet defined (will pass after Task 1).

**Step 3: Add endpoints to queue routes**

In `backend/grimoire/api/routes/queue.py`, after the `get_queue_stats` endpoint (around line 86), add:

```python
@router.post("/pause")
async def pause_processing_queue() -> dict:
    """Pause the queue worker. In-flight tasks finish, but no new tasks start."""
    from grimoire.services.queue_processor import pause_queue, is_queue_paused
    pause_queue()
    return {"paused": is_queue_paused()}


@router.post("/resume")
async def resume_processing_queue() -> dict:
    """Resume the queue worker."""
    from grimoire.services.queue_processor import resume_queue, is_queue_paused
    resume_queue()
    return {"paused": is_queue_paused()}
```

**Step 4: Add `paused` field to `get_queue_stats`**

In the `get_queue_stats` function, add the paused state to the return. Change the return from `return stats` to:

```python
    from grimoire.services.queue_processor import is_queue_paused
    return {**stats.model_dump(), "paused": is_queue_paused()}
```

**Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_queue_pause.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add backend/grimoire/api/routes/queue.py backend/tests/test_queue_pause.py
git commit -m "feat: add pause/resume API endpoints"
```

---

### Task 3: Add Pause API Client to Frontend

**Files:**
- Modify: `frontend/src/api/products.ts`

**Step 1: Add pause/resume functions**

Add to end of `frontend/src/api/products.ts`:

```typescript
export async function pauseQueue(): Promise<{ paused: boolean }> {
  const response = await api.post<{ paused: boolean }>('/queue/pause');
  return response.data;
}

export async function resumeQueue(): Promise<{ paused: boolean }> {
  const response = await api.post<{ paused: boolean }>('/queue/resume');
  return response.data;
}
```

**Step 2: Commit**

```bash
git add frontend/src/api/products.ts
git commit -m "feat: add pause/resume queue API client functions"
```

---

### Task 4: Add Pause Button to Floating Toolbar

**Files:**
- Modify: `frontend/src/pages/Library.tsx`

**Step 1: Add pause state and import**

Add `pauseQueue` and `resumeQueue` to the import from `../api/products`:

```typescript
import { pauseQueue, resumeQueue } from '../api/products';
```

Add state after `showBulkEdit`:

```typescript
const [queuePaused, setQueuePaused] = useState(false);
```

Add handler:

```typescript
const handleTogglePause = useCallback(async () => {
  if (queuePaused) {
    await resumeQueue();
    setQueuePaused(false);
  } else {
    await pauseQueue();
    setQueuePaused(true);
  }
}, [queuePaused]);
```

**Step 2: Add Pause button to the floating toolbar**

In the floating toolbar `div` (the one that renders when `selectedIds.size > 0`), add a pause/resume button before "Edit Selected":

```tsx
<button
  onClick={handleTogglePause}
  className="rounded-md px-4 py-2 text-sm font-medium"
  style={{
    backgroundColor: queuePaused ? 'var(--color-warning)' : 'var(--color-surface-raised)',
    color: queuePaused ? 'white' : 'var(--color-text-secondary)',
    border: queuePaused ? 'none' : '1px solid var(--color-border)',
  }}
>
  {queuePaused ? 'Queue Paused' : 'Pause Queue'}
</button>
```

**Step 3: Commit**

```bash
git add frontend/src/pages/Library.tsx
git commit -m "feat: add pause queue button to floating toolbar"
```

---

### Task 5: Auto-Resume on Modal Close

**Files:**
- Modify: `frontend/src/pages/Library.tsx`

**Step 1: Update BulkEditModal onClose to auto-resume**

Replace the `BulkEditModal` render block with a version that auto-resumes:

```tsx
{showBulkEdit && (
  <BulkEditModal
    selectedProducts={displayProducts.filter(p => selectedIds.has(p.id))}
    onClose={() => {
      setShowBulkEdit(false);
      if (queuePaused) {
        resumeQueue();
        setQueuePaused(false);
      }
    }}
    onComplete={clearSelection}
  />
)}
```

**Step 2: Commit**

```bash
git add frontend/src/pages/Library.tsx
git commit -m "feat: auto-resume queue when bulk edit modal closes"
```

---

### Task 6: Run All Tests and Verify

**Step 1: Run backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests pass (including new pause tests).

**Step 2: TypeScript check**

Run: `cd frontend && npx -p typescript tsc --noEmit`
Expected: No type errors.

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: pause queue polish and fixes"
```
