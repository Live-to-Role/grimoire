# Grimoire

A self-hosted digital library manager for tabletop RPG content with AI-powered organization, search, and content extraction.

## Features

- **Library Management**: Scan folders for PDFs and build a searchable catalog
- **AI-Powered Identification**: Automatically identify RPG products using Ollama, OpenAI, or Anthropic
- **Codex Integration**: Look up and contribute product identifications to the shared Codex database
- **Cover Extraction**: Automatically extract cover images and thumbnails from PDFs
- **Metadata Extraction**: Extract page count, embedded metadata, text content, and more
- **Full-Text Search**: Search across titles, descriptions, and extracted text (SQLite FTS5)
- **Semantic Search**: Vector embeddings for meaning-based search using nomic-embed-text
- **Collections & Tags**: Organize products with custom collections and tags
- **Campaign Management**: Create campaigns with sessions and track which products you're running
- **Duplicate Detection**: Find exact (hash-based) and content-based duplicate PDFs
- **Bulk Operations**: Batch tagging, collection assignment, metadata updates, and deletions
- **Processing Queue**: Background processing with Redis-backed queue for large imports
- **Exclusion Rules**: Pattern-based rules to skip files during library scans
- **In-Browser PDF Viewer**: View PDFs directly in the app
- **Data Export**: Export your library data

## Quick Start

**This section is the Docker install.** If you would rather run Grimoire
directly on your machine — which is the usual choice on Windows — skip to
[Running Natively](#running-natively-without-docker) instead. The two installs
configure libraries differently, and mixing their steps is the most common way
to get stuck: `PDF_LIBRARY_PATH` and the `/library` paths below are **Docker
only** and do nothing in a native install.

### Prerequisites

- Docker and Docker Compose
- A folder containing your RPG PDFs
- **Ollama** (optional, for local AI-powered identification)

### Installing Ollama

Grimoire uses Ollama for local AI processing (metadata identification, embeddings). Install it before running Grimoire:

1. Download and install Ollama from [ollama.com](https://ollama.com/download)

2. Pull the required models:
   ```bash
   ollama pull gemma3:12b
   ollama pull nomic-embed-text
   ```

**Model recommendations based on your hardware:**

| GPU VRAM | Recommended Model | Notes |
|----------|-------------------|-------|
| 8GB+     | `gemma3:12b`      | Best accuracy for metadata extraction |
| 4-8GB    | `gemma3:4b`       | Good balance of speed and quality |
| CPU only | `gemma3:4b`       | Will run slower but works |

**Embedding model:** Always install `nomic-embed-text` for semantic search features.

3. Verify Ollama is running:
   ```bash
   ollama list
   ```

> **Note**: Ollama runs locally - no data leaves your computer. API keys for cloud providers (OpenAI, Anthropic) can be configured in Settings as alternatives.

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Live-to-Role/grimoire.git
   cd grimoire
   ```

2. Point Grimoire at your PDF folders:
   ```bash
   cp .env.example .env
   ```

   Now open `.env` in a text editor and set the host path of each library you
   want. All three are optional — any you leave blank fall back to the empty
   `./pdfs` folder.

   The lines below are the *contents of the `.env` file*, not commands to type
   into a terminal. Use forward slashes, on Windows too.

   ```ini
   # Windows example
   PDF_LIBRARY_PATH=D:/RPG/PDFs
   # macOS example
   # PDF_LIBRARY_PATH=/Users/yourname/Documents/RPG
   # Linux example
   # PDF_LIBRARY_PATH=/home/yourname/rpg-library

   # Optional additional libraries
   PDF_LIBRARY_PATH_2=/path/to/second/library
   PDF_LIBRARY_PATH_3=/path/to/third/library
   ```

   These are mounted read-only in the container at `/library`, `/library2` and
   `/library3`. Set them before the first start — bind mounts are fixed when the
   containers are created, so changing a path later needs a `down` then `up`.

3. Start the services:
   ```bash
   docker compose -f docker/docker-compose.yml --project-directory . up -d
   ```

   > **Note**: `--project-directory .` is required. Without it, Compose resolves
   > the build context relative to `docker/` and the build fails.

   This starts five services:
   - **frontend** - The web UI, served by nginx (port 5173)
   - **grimoire** - The API server (port 8000)
   - **queue-worker** - Processes queued PDFs: text extraction, covers, AI
     identification, embeddings. If this one is not running, everything stays
     at "pending" forever
   - **worker** - Schedules periodic folder scans (Huey with 2 threads)
   - **redis** - Message queue and cache (port 6379)

4. Access the app:
   - **App**: http://localhost:5173
   - **API Docs**: http://localhost:8000/api/docs

   The API takes up to a minute to finish starting. Until it is ready,
   `docker compose ps` shows `grimoire` as `health: starting`.

5. Configure your library:
   - Go to **Settings** in the app
   - Under **Library Folders**, add the **container** paths — `/library`,
     `/library2`, `/library3` — not the host paths you put in `.env`

     Grimoire runs inside the container, so `C:/Users/you/Documents/RPG` does
     not exist as far as it is concerned. `PDF_LIBRARY_PATH` in `.env` is what
     makes that folder appear at `/library` inside the container; the app only
     ever sees the `/library` name.
   - In Grimoire, nav to **Manage**. Start **Scan** to discover your PDFs

   > If adding `/library` is rejected with "not mounted in the container", the
   > bind mount never happened — `PDF_LIBRARY_PATH` was empty or was set after
   > the containers were created. Fix `.env`, then `down` and `up -d` to
   > recreate them; editing `.env` alone will not move an existing mount.

### Configuring AI Providers

Grimoire supports multiple AI providers for metadata identification:

| Provider | Type | Cost | Configuration |
|----------|------|------|---------------|
| **Ollama** | Local | Free | Install Ollama + models on host machine |
| **Anthropic** | Cloud | Paid | Add API key in Settings |
| **OpenAI** | Cloud | Paid | Add API key in Settings |
| **Codex** | API | Free | Built-in lookup against the shared Codex database |

**For Docker users with Ollama:**

Since Grimoire runs in Docker, it needs to reach Ollama on your host machine. Configure the Ollama Base URL in **Settings**:

- **Windows/macOS**: `http://host.docker.internal:11434` (default in Docker)
- **Linux**: `http://172.17.0.1:11434` (or your Docker bridge IP)

Alternatively, set the environment variable in your `.env` file:
```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

**Priority order**: Settings UI > Environment variables > Default (`http://localhost:11434`)

### Changing Library Paths Later

Edit the `PDF_LIBRARY_PATH` values in `.env`, then recreate the containers so the
new mounts take effect — a restart is not enough:

```bash
docker compose -f docker/docker-compose.yml --project-directory . down
docker compose -f docker/docker-compose.yml --project-directory . up -d
```

| `.env` variable | Container path to enter in Settings |
|-----------------|-------------------------------------|
| `PDF_LIBRARY_PATH` | `/library` |
| `PDF_LIBRARY_PATH_2` | `/library2` |
| `PDF_LIBRARY_PATH_3` | `/library3` |

> **Important**: Enter the container path (e.g. `/library2`), not your host path.

## Running Natively (without Docker)

Grimoire can run directly on your machine without Docker.

### System Prerequisites

#### Python & Node.js
- **Python 3.11+**
- **Node.js 18+**

#### Tesseract OCR (required for text extraction from image-based PDFs)

| Platform | Install Command |
|----------|----------------|
| **Windows** | Download installer from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) — installs to `C:\Program Files\Tesseract-OCR\` |
| **macOS** | `brew install tesseract` |
| **Linux** | `sudo apt-get install tesseract-ocr` |

Verify: `tesseract --version`

If Tesseract is not on your PATH, set `TESSERACT_CMD` in your `.env` file:
```bash
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

#### Poppler (required for PDF-to-image conversion)

| Platform | Install Command |
|----------|----------------|
| **Windows** | `conda install -c conda-forge poppler` or download from [poppler releases](https://github.com/osber/poppler-windows/releases) |
| **macOS** | `brew install poppler` |
| **Linux** | `sudo apt-get install poppler-utils` |

Verify: `pdftoppm -v`

If Poppler is not on your PATH, set `POPPLER_PATH` in your `.env` file:
```bash
POPPLER_PATH=C:\poppler\Library\bin
```

### Native Installation

1. Clone and install backend dependencies:
   ```bash
   git clone https://github.com/Live-to-Role/grimoire.git
   cd grimoire/backend
   pip install -r requirements.txt
   ```

2. Install frontend dependencies:
   ```bash
   cd ../frontend
   npm install
   ```

3. Start the application using the provided scripts:
   ```bash
   # Windows (interactive — keeps a window open, stops everything on keypress)
   start.bat

   # Windows (detached — starts and returns; use this over a remote shell)
   start-headless.bat

   # macOS / Linux
   ./start.sh
   ```

   `start.bat` ends in a `pause`, and stops every service when that keypress
   arrives. Run it where stdin is not a console and `pause` reads EOF, returns
   instantly, and tears down everything it just launched. Use
   `start-headless.bat` whenever you are not sitting at the machine — over SSH,
   from a remote shell, or from a scheduled task. It launches the services
   detached, waits for the API to answer, and exits.

4. Stop the application:
   ```bash
   # Windows
   stop.bat

   # macOS / Linux
   ./stop.sh
   ```

   `stop.bat` matches on command lines rather than window titles, so it works no
   matter how the services were started.

5. Access the app at http://localhost:5173

6. Configure your library:
   - Go to **Settings** in the app
   - Under **Library Folders**, add the **real path to your PDFs on this
     machine** — for example `C:\Users\you\Documents\RPG` on Windows, or
     `/home/you/rpg-library` on Linux. Use the **Select Folder** button to
     browse to it rather than typing it
   - Nav to **Manage** and start a **Scan** to discover your PDFs

   > **`PDF_LIBRARY_PATH` in `.env` does nothing in a native install.** It is
   > read only by Docker Compose, to decide what to bind-mount into the
   > container. Likewise `/library`, `/library2` and `/library3` exist only
   > inside the Docker stack — entering them here will be rejected, because on
   > this machine there is no such folder. A native install has no indirection:
   > Grimoire reads the folder you name, directly.

**Four processes make up a native install.** The start scripts launch all four;
if you start things by hand, start all four or Grimoire will look healthy while
nothing is ever processed:

| Process | Command (run from `backend/`) | Without it |
|---------|-------------------------------|------------|
| API | `uvicorn grimoire.main:app --host 0.0.0.0 --port 8000` | No app at all |
| **Queue worker** | `python -m grimoire.worker.run` | **Everything sits at "pending" forever** |
| Scan worker | `python -m huey.bin.huey_consumer grimoire.worker.tasks.huey -w 2 -k thread` | Periodic folder scans never run |
| Frontend | `npm run dev` (from `frontend/`) | No web UI |

> **Note**: When running natively, Ollama URL defaults to `http://localhost:11434` (no `host.docker.internal` needed). Redis is optional — the queue falls back to SQLite-based processing.

## Troubleshooting

### Generate a diagnostic report

**Settings → Diagnostics → Generate Diagnostic Report.**

The report names the problem in plain language, and **Copy** / **Download** give
you a Markdown blob to paste into a bug report. It covers:

- whether the queue worker process is actually alive, and whether it is paused
- queue counts, the age of the oldest pending item, and recent error messages
- each library folder as the *server* sees it — exists, readable, product count
- whether Ollama is reachable, and which models it has
- OS, CPU count, RAM, free disk, and whether Grimoire is running in Docker

API keys and secrets are never included — only whether each one is set.

### Nothing is processing / everything is stuck at "pending"

Two very different causes look identical from the queue count, and the
diagnostic report tells them apart:

1. **Grimoire is paused.** The status widget in the bottom-right reads
   **"Grimoire Paused"**. Grimoire starts paused on every launch so it never
   competes with you for CPU. Flip the toggle to **"Grimoire Working"**.
2. **The queue worker is not running.** The report says
   *"the background worker is not running (no recent heartbeat)"*.
   - Docker: `docker compose -f docker/docker-compose.yml --project-directory . ps`
     — the `queue-worker` service must be up.
   - Native: the "Grimoire Queue Worker" process (`python -m grimoire.worker.run`)
     must be running. Re-run `start.bat` / `start-headless.bat` / `./start.sh`.

If the GPU sits near idle while items are pending, nothing is being sent to
Ollama at all — that is this problem, not a model or GPU problem.

### A library folder is rejected when I add it

Grimoire tells you which deployment it thinks it is in, and the fix is opposite
in each:

| Message | Fix |
|---------|-----|
| `... only exists inside the Docker stack, and Grimoire is running natively here` | You are running natively. Enter the real path on your machine (`C:\Users\you\Documents\RPG`), not `/library`. `PDF_LIBRARY_PATH` in `.env` does nothing here |
| `... is a path on your computer, and Grimoire is running inside Docker` | You are running Docker. Enter `/library` (or `/library2` / `/library3`) and point `PDF_LIBRARY_PATH` at the folder in `.env` |
| `... is not mounted in the container` | Docker, but the bind mount never happened. Set `PDF_LIBRARY_PATH`, then `down` and `up -d` — mounts are fixed when containers are created |

Not sure which one you are running? **Settings → Diagnostics → Generate
Diagnostic Report** reports it as `in_container`.

### "Select Folder" says it could not open the folder

The modal now shows the server's own message. The common ones:

| Message | Cause |
|---------|-------|
| `... does not exist on the server` | In Docker, you entered a host path. Use the container path (`/library`, `/library2`, `/library3`) — the **Library** shortcuts at the top of the modal jump straight there |
| `Permission denied reading ...` | The host folder mounted there is not readable by the container |
| `No response from the Grimoire API` | The API is still starting. It takes up to a minute on a cold start |

## Development

### Running in Development Mode

```bash
docker compose -f docker/docker-compose.dev.yml --project-directory . up
```

This mounts the backend source for hot-reloading. The dev stack runs the API,
both workers and Redis only — no frontend container — so run the Vite dev server
on the host alongside it:
```bash
cd frontend
npm install
npm run dev
```

### Running Tests

```bash
cd backend
python -m pytest tests/ -v
```

### API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

### Project Structure

```
grimoire/
├── backend/
│   ├── grimoire/
│   │   ├── api/routes/      # FastAPI route handlers
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic schemas
│   │   ├── services/        # Business logic
│   │   ├── processors/      # PDF extraction pipelines
│   │   ├── middleware/       # Rate limiting, caching, security
│   │   ├── worker/          # Huey background tasks
│   │   ├── config.py        # Configuration
│   │   └── main.py          # App entry point
│   ├── tests/               # pytest test suite
│   └── pyproject.toml
├── frontend/                # React/TypeScript SPA
│   └── src/
│       ├── pages/           # Library, Settings, Campaigns, LibraryManagement
│       ├── components/      # UI components
│       ├── api/             # API client
│       ├── hooks/           # Custom React hooks
│       └── types/           # TypeScript definitions
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── nginx.conf
│   ├── docker-compose.yml
│   └── docker-compose.dev.yml
└── docs/
    └── plans/               # Design and implementation plans
```

### Tech Stack

**Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.x (async), SQLite/aiosqlite, Redis, Huey

**Frontend**: React 19, TypeScript, Vite, TailwindCSS, React Query v5, Zustand

## API Endpoints

### Products
- `GET /api/v1/products` - List products with filtering and pagination
- `GET /api/v1/products/{id}` - Get product details
- `PATCH /api/v1/products/{id}` - Update product metadata
- `DELETE /api/v1/products/{id}` - Remove product from library
- `GET /api/v1/products/{id}/cover` - Get cover image
- `GET /api/v1/products/{id}/pdf` - View PDF

### Collections
- `GET /api/v1/collections` - List collections
- `POST /api/v1/collections` - Create collection
- `GET /api/v1/collections/{id}` - Get collection with products
- `PATCH /api/v1/collections/{id}` - Update collection
- `DELETE /api/v1/collections/{id}` - Delete collection

### Tags
- `GET /api/v1/tags` - List tags
- `POST /api/v1/tags` - Create tag
- `PATCH /api/v1/tags/{id}` - Update tag
- `DELETE /api/v1/tags/{id}` - Delete tag

### Folders & Scanning
- `GET /api/v1/folders` - List watched folders
- `POST /api/v1/folders` - Add watched folder
- `POST /api/v1/folders/scan` - Trigger library scan
- `GET /api/v1/library/stats` - Get library statistics

### Search
- `GET /api/v1/search?q=query` - Full-text search
- `POST /api/v1/semantic/search` - Semantic similarity search

### AI & Identification
- `POST /api/v1/ai/identify/{id}` - AI-identify a product
- `GET /api/v1/ai/codex/{id}` - Look up product in Codex

### Campaigns
- `GET /api/v1/campaigns` - List campaigns
- `POST /api/v1/campaigns` - Create campaign
- `GET /api/v1/campaigns/{id}` - Get campaign with sessions
- `PATCH /api/v1/campaigns/{id}` - Update campaign
- `DELETE /api/v1/campaigns/{id}` - Delete campaign

### Bulk Operations
- `POST /api/v1/bulk/tags` - Bulk add/remove tags
- `POST /api/v1/bulk/collections` - Bulk add/remove from collections
- `POST /api/v1/bulk/update` - Bulk update metadata
- `POST /api/v1/bulk/delete` - Bulk delete products

### Queue
- `GET /api/v1/queue/status` - Processing queue status
- `POST /api/v1/queue/retry` - Retry failed items

### Other
- `GET /api/v1/filters` - Available filter options
- `GET /api/v1/duplicates` - Duplicate detection
- `GET /api/v1/exclusions` - Exclusion rules
- `GET /api/v1/export` - Export library data
- `GET /api/v1/health` - Health check and diagnostics

## License

GPL-3.0

## Contributing

See [CONTRIBUTING.md](docs/contributing.md) for guidelines.
