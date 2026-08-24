# Native Deployment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run grimoire natively on the host (no Docker required) so the folder browser sees the real filesystem, USB drives, and all user directories.

**Architecture:** Remove Docker as a requirement. Backend runs via `uvicorn`, Huey worker runs as a separate process, frontend runs via `npm run dev` or serves built assets. Redis becomes optional (already has graceful fallback). Startup scripts automate the process for non-technical users.

**Tech Stack:** Python 3.11+, Node.js 20+, SQLite (already used), Huey with SQLite backend (already used)

---

### Task 1: Update .env defaults for native deployment

**Files:**
- Modify: `.env`
- Modify: `.env.example`

**Step 1: Update `.env` for native host paths**

Replace the current `.env` with native-friendly defaults:

```env
# Library Configuration
# Note: Library paths are now managed via watched folders in the UI
# These env vars are no longer needed for Docker volume mounts

# Tesseract OCR
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/grimoire.db

# Server Configuration
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
DEBUG=false

# Processing
MAX_CONCURRENT_PROCESSING=3
COVER_THUMBNAIL_SIZE=300

# AI Providers (optional - can also be configured in user settings)
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
# GOOGLE_API_KEY=
OLLAMA_BASE_URL=http://localhost:11434

# Security
SECRET_KEY=dev-secret-key-change-in-production

# Codex API (CODEX_API_KEY is configured in user settings)
CODEX_API_URL=https://codex-api.livetorole.com/api/v1
CODEX_CONTRIBUTE_ENABLED=true
CODEX_TIMEOUT=10
```

Key changes:
- Remove `PDF_LIBRARY_PATH`, `PDF_LIBRARY_PATH_2`, `PDF_LIBRARY_PATH_3` (no longer needed — folders managed via UI)
- Change `OLLAMA_BASE_URL` from `host.docker.internal:11434` to `localhost:11434`
- Remove `REDIS_URL` (not needed)

**Step 2: Update `.env.example`**

```env
# Library Configuration
# Folders are managed via the Settings UI — no path configuration needed here

# Server Configuration
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
DEBUG=false

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/grimoire.db

# AI Providers (optional - leave empty to disable)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
OLLAMA_BASE_URL=http://localhost:11434

# Processing
MAX_CONCURRENT_PROCESSING=3
COVER_THUMBNAIL_SIZE=300

# Security
SECRET_KEY=change-this-in-production

# Codex API (optional - for syncing to Codex database)
CODEX_API_URL=https://codex-api.livetorole.com/api/v1
CODEX_API_KEY=
CODEX_CONTRIBUTE_ENABLED=false
CODEX_TIMEOUT=10

# OCR (optional - set path to tesseract if not on system PATH)
# Windows: TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
# macOS/Linux: leave empty to use system PATH
TESSERACT_CMD=
# Poppler (required for OCR - pdf2image needs pdftoppm)
# Windows: POPPLER_PATH=C:\poppler\Library\bin
# macOS (brew): leave empty
# Install via conda: conda install -c conda-forge poppler
POPPLER_PATH=
```

> **Note:** In Docker, `poppler-utils` is pre-installed in the image. For native deployment,
> poppler must be installed separately. The backend auto-detects common install locations
> (including conda at `~/miniconda3/Library/bin`), but you can set `POPPLER_PATH` explicitly
> if needed. Without poppler, OCR extraction will fail with
> `Unable to get page count. Is poppler installed and in PATH?`

**Step 3: Commit**

```bash
git add .env .env.example
git commit -m "chore: update env defaults for native deployment"
```

---

### Task 2: Update config.py defaults

**Files:**
- Modify: `backend/grimoire/config.py`

**Step 1: Change `library_path` default and make `redis_url` optional**

In `backend/grimoire/config.py`, change:

```python
# Redis
redis_url: str = "redis://localhost:6379/0"

# Paths
data_dir: Path = Path("./data")
library_path: Path = Path("/library")
covers_dir: Path = Path("./data/covers")
```

To:

```python
# Redis (optional — app works without it)
redis_url: str = "redis://localhost:6379/0"

# Paths
data_dir: Path = Path("./data")
library_path: Path = Path("./pdfs")
covers_dir: Path = Path("./data/covers")
```

This changes the `library_path` default from `/library` (Docker container path) to `./pdfs` (relative host path).

**Step 2: Run existing tests to verify nothing breaks**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All 26 tests PASS

**Step 3: Commit**

```bash
git add backend/grimoire/config.py
git commit -m "chore: update config defaults for native deployment"
```

---

### Task 3: Create startup scripts

**Files:**
- Create: `start.sh` (Linux/macOS)
- Create: `start.bat` (Windows)

**Step 1: Create `start.sh`**

```bash
#!/usr/bin/env bash
set -e

echo "=== Grimoire - Starting ==="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is required. Install from https://www.python.org/"
    exit 1
fi

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js is required. Install from https://nodejs.org/"
    exit 1
fi

# Create data directories
mkdir -p data/covers

# Install backend dependencies if needed
if [ ! -d "backend/.venv" ]; then
    echo "Setting up Python virtual environment..."
    python3 -m venv backend/.venv
fi

source backend/.venv/bin/activate

echo "Installing backend dependencies..."
pip install -q -r backend/requirements.txt

# Install frontend dependencies if needed
if [ ! -d "frontend/node_modules" ]; then
    echo "Installing frontend dependencies..."
    cd frontend && npm install && cd ..
fi

# Copy .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

echo ""
echo "Starting Grimoire..."
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
echo "  API Docs: http://localhost:8000/api/docs"
echo ""
echo "Press Ctrl+C to stop all services."
echo ""

# Start backend
cd backend
PYTHONPATH=. python -m uvicorn grimoire.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Start Huey worker
PYTHONPATH=. python -m huey.bin.huey_consumer grimoire.worker.tasks.huey -w 2 -k thread &
WORKER_PID=$!
cd ..

# Start frontend
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

# Cleanup on exit
cleanup() {
    echo ""
    echo "Stopping Grimoire..."
    kill $BACKEND_PID $WORKER_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $WORKER_PID $FRONTEND_PID 2>/dev/null
    echo "Goodbye!"
}
trap cleanup EXIT INT TERM

# Wait for any process to exit
wait
```

**Step 2: Create `start.bat`**

```batch
@echo off
echo === Grimoire - Starting ===
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3 is required. Install from https://www.python.org/
    exit /b 1
)

REM Check Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is required. Install from https://nodejs.org/
    exit /b 1
)

REM Create data directories
if not exist "data\covers" mkdir data\covers

REM Set up Python venv if needed
if not exist "backend\.venv" (
    echo Setting up Python virtual environment...
    python -m venv backend\.venv
)

call backend\.venv\Scripts\activate.bat

echo Installing backend dependencies...
pip install -q -r backend\requirements.txt

REM Install frontend dependencies if needed
if not exist "frontend\node_modules" (
    echo Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
)

REM Copy .env if it doesn't exist
if not exist ".env" (
    echo Creating .env from .env.example...
    copy .env.example .env
)

echo.
echo Starting Grimoire...
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo   API Docs: http://localhost:8000/api/docs
echo.
echo Press Ctrl+C to stop all services.
echo.

REM Start backend
cd backend
start "Grimoire Backend" cmd /c "set PYTHONPATH=. && python -m uvicorn grimoire.main:app --host 0.0.0.0 --port 8000 --reload"

REM Start Huey worker
start "Grimoire Worker" cmd /c "set PYTHONPATH=. && python -m huey.bin.huey_consumer grimoire.worker.tasks.huey -w 2 -k thread"
cd ..

REM Start frontend
cd frontend
start "Grimoire Frontend" cmd /c "npm run dev"
cd ..

echo All services started. Close the terminal windows to stop.
pause
```

**Step 3: Make shell script executable and commit**

```bash
chmod +x start.sh
git add start.sh start.bat
git commit -m "feat: add native startup scripts for Windows, macOS, and Linux"
```

---

### Task 4: Update the folder browser default to be OS-aware

**Files:**
- Modify: `backend/grimoire/api/routes/folders.py`

**Step 1: Make the browse default smarter for native deployment**

Currently defaults to `Path("/")`. For native deployment, `Path.home()` is more useful (user's actual home directory). On Windows, `Path("/")` resolves to `C:\` which is less useful as a starting point.

Change the default in `backend/grimoire/api/routes/folders.py`:

```python
@router.get("/browse", response_model=BrowseResponse)
async def browse_directories(path: str | None = Query(None, description="Directory path to browse")) -> BrowseResponse:
    """Browse server filesystem directories for folder selection."""
    if path:
        browse_path = Path(path).resolve()
    else:
        browse_path = Path.home()
```

Change `Path("/")` back to `Path.home()` — now that we're running natively, the home directory is the user's actual home, not `/root` in a container.

**Step 2: Update the test**

In `backend/tests/api/test_browse.py`, update:

```python
async def test_browse_default_returns_home():
    """Browse with no path returns home directory."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/folders/browse")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_path"] == str(Path.home())
    assert isinstance(data["directories"], list)
```

**Step 3: Run tests**

Run: `cd backend && python -m pytest tests/api/test_browse.py -v`
Expected: All 5 tests PASS

**Step 4: Commit**

```bash
git add backend/grimoire/api/routes/folders.py backend/tests/api/test_browse.py
git commit -m "fix: browse defaults to home directory for native deployment"
```

---

### Task 5: Move Docker files to docker/ directory

**Files:**
- Move: `docker-compose.yml` → `docker/docker-compose.yml`
- Move: `docker-compose.dev.yml` → `docker/docker-compose.dev.yml`

**Step 1: Move docker-compose files**

```bash
git mv docker-compose.yml docker/docker-compose.yml
git mv docker-compose.dev.yml docker/docker-compose.dev.yml
```

Docker files still work for users who want them, just organized under `docker/`.

**Step 2: Commit**

```bash
git add -A
git commit -m "chore: move docker-compose files to docker/ directory"
```

---

### Task 6: Run all tests and verify

**Step 1: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All 26 tests PASS

**Step 2: Verify frontend compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Test native startup manually**

1. Stop any running Docker containers: `docker compose -f docker-compose.dev.yml down`
2. Run: `./start.sh` (Linux/macOS) or `start.bat` (Windows)
3. Open `http://localhost:5173`
4. Go to Settings → Click Browse → Verify you see your actual home directory
5. Navigate to a PDF folder (e.g., `D:\Drivethrurpg`)
6. Select it and add it as a library folder
7. Verify the folder is added successfully
