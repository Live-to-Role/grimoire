@echo off
echo === Grimoire - Stopping ===

REM Find services by command line, not window title: under Windows Terminal the
REM service windows don't carry their launch titles, so the old
REM `taskkill /FI "WINDOWTITLE eq ..."` matched nothing and services survived.
REM Kill the payload processes (python/node) with their trees; the cmd /c hosts
REM then exit normally and their windows close on their own.
powershell -NoProfile -Command ^
  "$targets = Get-CimInstance Win32_Process | Where-Object { $_.Name -ne 'cmd.exe' -and ($_.CommandLine -match 'uvicorn grimoire\.main|grimoire\.worker\.run|huey_consumer grimoire\.worker' -or ($_.Name -match '^node' -and $_.CommandLine -match 'grimoire[\\/]frontend')) }; if (-not $targets) { Write-Host 'No running Grimoire services found.' } else { foreach ($t in $targets) { Write-Host ('Stopping ' + $t.Name + ' (pid ' + $t.ProcessId + ')'); taskkill /PID $t.ProcessId /T /F >$null 2>&1 } }"

echo Done.
