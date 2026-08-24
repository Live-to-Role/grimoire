# Folder Browser for Library Folders

## Problem
The "Add Library Folder" input requires users to type folder paths manually, which is not user-friendly.

## Solution
Add a "Browse" button that opens a server-side folder browser modal, allowing users to navigate and select folders visually.

## Backend

### New endpoint: `GET /folders/browse`
- Optional query param: `path` (string)
- If no `path` provided, returns user's home directory listing
- Returns only directories (no files), sorted alphabetically, hidden dirs excluded
- Response schema:
  ```json
  {
    "current_path": "/home/user/Documents",
    "parent_path": "/home/user",
    "directories": [
      { "name": "RPG Books", "path": "/home/user/Documents/RPG Books" }
    ]
  }
  ```
- `parent_path` is `null` when at filesystem root
- Validates path exists and is accessible; returns 400/404 otherwise
- Cross-platform via `pathlib.Path` — works on Windows, Mac, Linux

## Frontend

### Browse button
- Folder icon button added next to the path text input

### Modal dialog
- Header showing current path
- "Up" button to navigate to parent directory
- Scrollable list of subdirectories, clickable to navigate deeper
- "Select" button to confirm current directory
- "Cancel" button to close without selecting
- On selection, populates the existing path text input

## Cross-platform
- `Path.home()` for starting directory
- `pathlib` for all path handling — no hardcoded separators
- Backend normalizes paths so frontend is OS-agnostic
