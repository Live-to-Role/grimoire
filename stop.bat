@echo off
REM Stop all Grimoire services. Safe to run remotely - needs no keypress and
REM touches no windows.
REM
REM Why this matches on command lines instead of window titles: the
REM "taskkill /FI WINDOWTITLE eq Grimoire Backend*" filters that start.bat uses
REM only match when the services were launched by start.bat in an interactive
REM desktop session. Otherwise they silently match nothing - taskkill prints
REM "No tasks running" and still exits 0, so the failure is invisible. Matching
REM the command line works no matter how the services were started.

echo === Grimoire - Stopping ===
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-services.ps1"
set RC=%ERRORLEVEL%

echo.
if not "%RC%"=="0" (
    echo Some processes could not be stopped.
    exit /b %RC%
)
echo Goodbye!
