# Native Deployment Design

## Problem
Running in Docker prevents the folder browser from seeing the host filesystem, USB drives, and user directories. Users need Docker knowledge to configure volume mounts, which is not accessible to non-technical users.

## Solution
Run the backend, worker, and frontend natively on the host. Drop the Redis dependency (already has graceful fallback). Provide a simple startup script.

## What Changes

### Backend + Worker
- Run directly on host with Python
- `uvicorn grimoire.main:app` for the API
- `huey_consumer` for background tasks
- Both see the host filesystem natively — browse, USB drives, any path works

### Frontend
- `npm run dev` (development) or serve built `dist/` folder
- No nginx container needed

### Redis
- Drop the dependency entirely
- Cache service already degrades gracefully — filter queries go directly to SQLite
- For a local single-user app, performance difference is negligible

### Ollama
- URL changes from `host.docker.internal:11434` to `localhost:11434`

## What Gets Created

### Startup script (`start.sh` / `start.bat`)
1. Ensures Python dependencies are installed
2. Creates `data/` and `data/covers/` directories
3. Starts the backend + worker
4. Starts the frontend dev server (or serves built assets)

## What Gets Updated

- `.env` defaults: remove Docker-isms (`host.docker.internal` → `localhost`, container paths → relative paths)
- `config.py`: `library_path` default from `/library` to `./pdfs`
- Docker files remain for users who prefer Docker, but become optional

## What Stays the Same

- All application code, database, schemas, API endpoints
- SQLite database at `./data/grimoire.db`
- Huey worker with SQLite backend (already non-Docker)
