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

# Create data directories (inside backend/ where the database lives)
mkdir -p backend/data/covers

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
