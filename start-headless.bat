@echo off
REM Start all Grimoire services and exit immediately - no "press any key" pause.
REM
REM Use this over start.bat when you are not sitting at the machine (SSH, remote
REM shell, scheduled task). start.bat ends in a `pause` and stops every service
REM when that keypress arrives, which makes it unusable headlessly: run it where
REM stdin is not a console and `pause` reads EOF, returns instantly, and tears
REM down everything it just launched.
REM
REM Services are launched detached, so they keep running after this script (and
REM the shell that ran it) exits. Stop them with stop.bat.

echo === Grimoire - Starting (headless) ===
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3 is required. Install from https://www.python.org/
    exit /b 1
)

node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is required. Install from https://nodejs.org/
    exit /b 1
)

if not exist "backend\data\covers" mkdir backend\data\covers

if not exist "backend\.venv" (
    echo Setting up Python virtual environment...
    python -m venv backend\.venv
)

REM Install/update backend deps only when requirements.txt changes
REM (fc returns errorlevel 1 if the files differ or the stamp is missing)
fc /b backend\requirements.txt backend\.venv\.requirements.stamp >nul 2>&1
if errorlevel 1 (
    echo Installing backend dependencies...
    backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    copy /y backend\requirements.txt backend\.venv\.requirements.stamp >nul
) else (
    echo Backend dependencies already up to date.
)

if not exist "frontend\node_modules" (
    echo Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
)

if not exist ".env" (
    echo Creating .env from .env.example...
    copy .env.example .env >nul
)

echo.
echo Starting services...

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-services.ps1"
set RC=%ERRORLEVEL%

echo.
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo   API Docs: http://localhost:8000/api/docs
echo.
if not "%RC%"=="0" (
    echo Started, but the backend did not come up cleanly - see above.
    exit /b %RC%
)
echo Services started detached. Stop them with stop.bat.
