#!/usr/bin/env bash
set -e

echo "=== Grimoire - Starting ==="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is required."
    echo "  sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js is required."
    echo "  curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -"
    echo "  sudo apt install -y nodejs"
    exit 1
fi

# Resolve script directory so it works when called from any path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create data directories (inside backend/ where the database lives)
mkdir -p backend/data/covers

# Set up Python venv if needed
if [ ! -d "backend/.venv" ]; then
    echo "Setting up Python virtual environment..."
    python3 -m venv backend/.venv
fi

source backend/.venv/bin/activate

# Install/update backend deps only when requirements.txt changes
# (cmp -s exits non-zero if the files differ or the stamp is missing)
if ! cmp -s backend/requirements.txt backend/.venv/.requirements.stamp; then
    echo "Installing backend dependencies..."
    pip install -r backend/requirements.txt
    cp backend/requirements.txt backend/.venv/.requirements.stamp
else
    echo "Backend dependencies already up to date."
fi

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

# Detect LAN IP for display (useful for Pi/headless access)
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
LAN_IP=${LAN_IP:-localhost}

echo ""
echo "Starting Grimoire..."
echo "  Backend:  http://${LAN_IP}:8000"
echo "  Frontend: http://${LAN_IP}:5173"
echo "  API Docs: http://${LAN_IP}:8000/api/docs"
echo ""
echo "Press Ctrl+C to stop all services."
echo ""

# Start backend
cd backend
PYTHONPATH=. python3 -m uvicorn grimoire.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Start dedicated queue worker (owns heavy ProcessingQueue draining, out of the API process)
PYTHONPATH=. python3 -m grimoire.worker.run &
QUEUE_WORKER_PID=$!

# Start Huey worker (folder scan scheduling only)
PYTHONPATH=. python3 -m huey.bin.huey_consumer grimoire.worker.tasks.huey -w 2 -k thread &
WORKER_PID=$!
cd ..

# Start frontend
cd frontend
npm run dev -- --host &
FRONTEND_PID=$!
cd ..

# Cleanup on exit
cleanup() {
    echo ""
    echo "Stopping Grimoire..."
    kill $BACKEND_PID $QUEUE_WORKER_PID $WORKER_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $QUEUE_WORKER_PID $WORKER_PID $FRONTEND_PID 2>/dev/null
    echo "Goodbye!"
}
trap cleanup EXIT INT TERM

# Wait for any process to exit
wait
