# Launch every Grimoire service detached, then return immediately.
#
# Uses Start-Process rather than cmd's `start`: `start` needs a console to spawn
# its window, so under a console-less parent (a remote shell, a scheduled task,
# an agent harness) it never hands control back and the caller hangs even though
# the services came up fine. Start-Process detaches correctly in both cases.

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host ('ERROR: venv python not found at ' + $python)
    Write-Host 'Run start.bat once (or create backend\.venv) before using this script.'
    exit 1
}

# Each service is launched through cmd /c so PYTHONPATH is set the same way
# start.bat sets it, keeping the two entry points behaviourally identical.
$services = @(
    @{ Name = 'Backend';      Dir = $backend;  Cmd = 'set PYTHONPATH=. && .venv\Scripts\python.exe -m uvicorn grimoire.main:app --host 0.0.0.0 --port 8000 --reload' },
    @{ Name = 'Queue Worker'; Dir = $backend;  Cmd = 'set PYTHONPATH=. && .venv\Scripts\python.exe -m grimoire.worker.run' },
    @{ Name = 'Scan Worker';  Dir = $backend;  Cmd = 'set PYTHONPATH=. && .venv\Scripts\python.exe -m huey.bin.huey_consumer grimoire.worker.tasks.huey -w 2 -k thread' },
    @{ Name = 'Frontend';     Dir = $frontend; Cmd = 'npm run dev' }
)

foreach ($service in $services) {
    Write-Host ('  starting ' + $service.Name)
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', $service.Cmd `
        -WorkingDirectory $service.Dir `
        -WindowStyle Minimized | Out-Null
}

# Confirm the API actually answers rather than just reporting "launched" - a
# service that dies on startup is otherwise indistinguishable from a healthy one.
#
# Deadline-based, not iteration-based: each probe can itself block for up to
# TimeoutSec, so a fixed loop count gives a wall-clock timeout that drifts with
# connection latency. A cold start here runs past a minute (uvicorn --reload
# plus model loading), so allow a generous budget.
$deadlineSeconds = 150
$timer = [Diagnostics.Stopwatch]::StartNew()
Write-Host ('  waiting for backend (up to ' + $deadlineSeconds + 's)...')

while ($timer.Elapsed.TotalSeconds -lt $deadlineSeconds) {
    try {
        $response = Invoke-WebRequest -Uri 'http://localhost:8000/api/v1/health' -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            Write-Host ('  backend healthy after ' + [int]$timer.Elapsed.TotalSeconds + 's.')
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 2
}

Write-Host ('  WARNING: backend did not answer /api/v1/health within ' + $deadlineSeconds + 's.')
Write-Host '  It may still be starting - re-check with: curl http://localhost:8000/api/v1/health'
exit 1
