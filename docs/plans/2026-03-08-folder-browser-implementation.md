# Folder Browser Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a folder browser modal so users can visually navigate and select directories instead of typing paths manually.

**Architecture:** New `GET /folders/browse` endpoint returns directory listings using `pathlib`. Frontend adds a "Browse" button that opens a modal with clickable directory navigation. On selection, the chosen path populates the existing text input.

**Tech Stack:** Python/FastAPI (backend endpoint), React/TypeScript (modal component), pathlib (cross-platform paths)

---

### Task 1: Backend — Browse endpoint schema

**Files:**
- Modify: `backend/grimoire/schemas/folder.py`

**Step 1: Add the browse response schemas to the folder schemas file**

Add to `backend/grimoire/schemas/folder.py`:

```python
class DirectoryEntry(BaseModel):
    """A single directory in a browse listing."""
    name: str
    path: str


class BrowseResponse(BaseModel):
    """Response for the folder browse endpoint."""
    current_path: str
    parent_path: str | None
    directories: list[DirectoryEntry]
```

**Step 2: Commit**

```bash
git add backend/grimoire/schemas/folder.py
git commit -m "feat: add browse response schemas for folder browser"
```

---

### Task 2: Backend — Browse endpoint

**Files:**
- Modify: `backend/grimoire/api/routes/folders.py`

**Step 1: Add the browse endpoint**

Add to `backend/grimoire/api/routes/folders.py`, before the existing routes (so `/browse` doesn't conflict with `/{folder_id}`):

```python
from grimoire.schemas.folder import BrowseResponse, DirectoryEntry

@router.get("/browse", response_model=BrowseResponse)
async def browse_directories(path: str | None = Query(None, description="Directory path to browse")) -> BrowseResponse:
    """Browse server filesystem directories for folder selection."""
    if path:
        browse_path = Path(path)
    else:
        browse_path = Path.home()

    if not browse_path.exists():
        raise HTTPException(status_code=404, detail="Path does not exist")
    if not browse_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    # Get parent path (None if at filesystem root)
    parent = browse_path.parent
    parent_path = str(parent) if parent != browse_path else None

    # List subdirectories, excluding hidden dirs
    directories = []
    try:
        for entry in sorted(browse_path.iterdir(), key=lambda e: e.name.lower()):
            if entry.is_dir() and not entry.name.startswith('.'):
                directories.append(DirectoryEntry(name=entry.name, path=str(entry)))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied accessing this directory")

    return BrowseResponse(
        current_path=str(browse_path),
        parent_path=parent_path,
        directories=directories,
    )
```

**Step 2: Update the import in the route file**

Update the import block at top of `folders.py` to include the new schemas:

```python
from grimoire.schemas.folder import (
    BrowseResponse,
    DirectoryEntry,
    LibraryStats,
    ScanRequest,
    ScanResponse,
    WatchedFolderCreate,
    WatchedFolderResponse,
    WatchedFolderUpdate,
)
```

**Step 3: Commit**

```bash
git add backend/grimoire/api/routes/folders.py
git commit -m "feat: add GET /folders/browse endpoint for directory navigation"
```

---

### Task 3: Backend — Test the browse endpoint

**Files:**
- Create: `backend/tests/test_browse.py`

**Step 1: Write tests**

```python
"""Tests for the folder browse endpoint."""

import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from grimoire.main import app


@pytest.fixture
def temp_dirs():
    """Create a temporary directory structure for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "FolderA").mkdir()
        (base / "FolderB").mkdir()
        (base / ".hidden").mkdir()
        yield str(base)


@pytest.mark.asyncio
async def test_browse_default_returns_home():
    """Browse with no path returns home directory."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_path"] == str(Path.home())
    assert isinstance(data["directories"], list)


@pytest.mark.asyncio
async def test_browse_specific_path(temp_dirs):
    """Browse a specific path returns its subdirectories."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": temp_dirs})
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_path"] == temp_dirs
    names = [d["name"] for d in data["directories"]]
    assert "FolderA" in names
    assert "FolderB" in names
    assert ".hidden" not in names


@pytest.mark.asyncio
async def test_browse_nonexistent_path():
    """Browse a nonexistent path returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": "/nonexistent/path/abc123"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_browse_parent_path(temp_dirs):
    """Browse returns correct parent path."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": temp_dirs})
    data = resp.json()
    assert data["parent_path"] == str(Path(temp_dirs).parent)


@pytest.mark.asyncio
async def test_browse_sorted_alphabetically(temp_dirs):
    """Directories are sorted alphabetically (case-insensitive)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse", params={"path": temp_dirs})
    data = resp.json()
    names = [d["name"] for d in data["directories"]]
    assert names == sorted(names, key=str.lower)
```

**Step 2: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_browse.py -v`
Expected: All 5 tests PASS

**Step 3: Commit**

```bash
git add backend/tests/test_browse.py
git commit -m "test: add tests for folder browse endpoint"
```

---

### Task 4: Frontend — FolderBrowserModal component

**Files:**
- Create: `frontend/src/components/FolderBrowserModal.tsx`

**Step 1: Create the modal component**

```tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FolderOpen, ChevronUp, X } from 'lucide-react';
import apiClient from '../api/client';

interface DirectoryEntry {
  name: string;
  path: string;
}

interface BrowseResponse {
  current_path: string;
  parent_path: string | null;
  directories: DirectoryEntry[];
}

interface FolderBrowserModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
}

export function FolderBrowserModal({ isOpen, onClose, onSelect }: FolderBrowserModalProps) {
  const [currentPath, setCurrentPath] = useState<string | undefined>(undefined);

  const { data, isLoading, error } = useQuery({
    queryKey: ['browse-directories', currentPath],
    queryFn: async () => {
      const params = currentPath ? { path: currentPath } : {};
      const res = await apiClient.get<BrowseResponse>('/folders/browse', { params });
      return res.data;
    },
    enabled: isOpen,
  });

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="mx-4 flex max-h-[70vh] w-full max-w-lg flex-col overflow-hidden rounded-xl bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-3">
          <h2 className="text-lg font-semibold text-neutral-900">Select Folder</h2>
          <button
            onClick={onClose}
            className="p-1 text-neutral-400 hover:text-neutral-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Current path */}
        <div className="flex items-center gap-2 border-b border-neutral-100 bg-neutral-50 px-4 py-2">
          {data?.parent_path && (
            <button
              onClick={() => setCurrentPath(data.parent_path!)}
              className="rounded p-1 text-neutral-500 hover:bg-neutral-200 hover:text-neutral-700"
              title="Go to parent directory"
            >
              <ChevronUp className="h-4 w-4" />
            </button>
          )}
          <p className="min-w-0 flex-1 truncate text-sm text-neutral-600">
            {data?.current_path || 'Loading...'}
          </p>
        </div>

        {/* Directory listing */}
        <div className="flex-1 overflow-auto p-2">
          {isLoading && (
            <div className="py-8 text-center text-sm text-neutral-500">Loading...</div>
          )}
          {error && (
            <div className="py-8 text-center text-sm text-red-500">
              Failed to load directory. Check that the path is accessible.
            </div>
          )}
          {data && data.directories.length === 0 && (
            <div className="py-8 text-center text-sm text-neutral-500">
              No subdirectories found
            </div>
          )}
          {data?.directories.map((dir) => (
            <button
              key={dir.path}
              onClick={() => setCurrentPath(dir.path)}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-neutral-700 hover:bg-purple-50 hover:text-purple-700"
            >
              <FolderOpen className="h-4 w-4 flex-shrink-0 text-amber-500" />
              <span className="truncate">{dir.name}</span>
            </button>
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-neutral-200 px-4 py-3">
          <button
            onClick={onClose}
            className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              if (data?.current_path) {
                onSelect(data.current_path);
                onClose();
              }
            }}
            disabled={!data?.current_path}
            className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            Select This Folder
          </button>
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/FolderBrowserModal.tsx
git commit -m "feat: add FolderBrowserModal component"
```

---

### Task 5: Frontend — Integrate browse button into Settings

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`

**Step 1: Add state and import**

Add import at top of `Settings.tsx`:

```tsx
import { FolderBrowserModal } from '../components/FolderBrowserModal';
```

Add state variable alongside the other folder-related state (after line 80):

```tsx
const [showBrowseModal, setShowBrowseModal] = useState(false);
```

**Step 2: Add Browse button next to the path input**

Replace the path `<input>` line (line 331-337) with the input + browse button:

```tsx
<input
  type="text"
  value={newFolderPath}
  onChange={(e) => setNewFolderPath(e.target.value)}
  placeholder="/path/to/pdfs"
  className="flex-1 rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
/>
<button
  onClick={() => setShowBrowseModal(true)}
  type="button"
  className="inline-flex items-center gap-1 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
  title="Browse folders"
>
  <FolderOpen className="h-4 w-4" />
  Browse
</button>
```

**Step 3: Add the modal at the bottom of the component (before closing `</div>` of the return)**

Add before the duplicate resolution modal (before line 571):

```tsx
{/* Folder Browser Modal */}
<FolderBrowserModal
  isOpen={showBrowseModal}
  onClose={() => setShowBrowseModal(false)}
  onSelect={(path) => setNewFolderPath(path)}
/>
```

**Step 4: Commit**

```bash
git add frontend/src/pages/Settings.tsx
git commit -m "feat: integrate folder browser modal into Settings page"
```

---

### Task 6: Manual verification

**Step 1: Start the backend**

Run: `cd backend && python -m uvicorn grimoire.main:app --reload`

**Step 2: Start the frontend**

Run: `cd frontend && npm run dev`

**Step 3: Verify the feature**

1. Navigate to Settings page
2. Click the "Browse" button next to the folder path input
3. Verify the modal opens showing home directory contents
4. Click a folder to navigate into it
5. Click the up arrow to go back
6. Click "Select This Folder" — verify the path populates the input
7. Click "Cancel" — verify modal closes without changing the input

**Step 4: Final commit if any fixes needed**
