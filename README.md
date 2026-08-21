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

   Edit `.env` and set the host path of each library you want. All three are
   optional — any you leave blank fall back to the empty `./pdfs` folder.

   ```bash
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

   This starts four services:
   - **frontend** - The web UI, served by nginx (port 5173)
   - **grimoire** - The API server (port 8000)
   - **worker** - Background task processor (Huey with 2 threads)
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
   - Click **Scan** in Library Management to discover your PDFs

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
   # Windows
   start.bat

   # macOS / Linux
   ./start.sh
   ```

   Or start services manually:
   ```bash
   # Terminal 1 - Backend
   cd backend
   uvicorn grimoire.main:app --host 0.0.0.0 --port 8000

   # Terminal 2 - Frontend
   cd frontend
   npm run dev
   ```

4. Access the app at http://localhost:5173

> **Note**: When running natively, Ollama URL defaults to `http://localhost:11434` (no `host.docker.internal` needed). Redis is optional — the queue falls back to SQLite-based processing.

## Development

### Running in Development Mode

```bash
docker compose -f docker/docker-compose.dev.yml --project-directory . up
```

This mounts the backend source for hot-reloading. The dev stack runs the API,
worker and Redis only — no frontend container — so run the Vite dev server on the
host alongside it:
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
