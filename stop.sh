#!/usr/bin/env bash
# Stop all Grimoire services started by start.sh (or manually).
# Matches by command line, mirroring stop.bat.

echo "=== Grimoire - Stopping ==="

stopped=0
stop_pattern() {
    if pkill -f "$1" 2>/dev/null; then
        echo "Stopped: $2"
        stopped=1
    fi
}

stop_pattern 'uvicorn grimoire\.main'            "backend (uvicorn)"
stop_pattern 'grimoire\.worker\.run'             "queue worker"
stop_pattern 'huey_consumer grimoire\.worker'    "scan worker (huey)"
stop_pattern 'node .*grimoire/frontend'          "frontend (vite)"

if [ "$stopped" -eq 0 ]; then
    echo "No running Grimoire services found."
fi
echo "Done."
