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

REM Create data directories (inside backend/ where the database lives)
if not exist "backend\data\covers" mkdir backend\data\covers

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
echo Press any key to stop all services.
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

echo All services started.
pause

echo.
echo Stopping Grimoire...
taskkill /FI "WINDOWTITLE eq Grimoire Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Grimoire Worker*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Grimoire Frontend*" /F >nul 2>&1
echo Goodbye!
