# Stop every running Grimoire service.
#
# Kept as a .ps1 rather than inlined into stop.bat: escaping a script this size
# through cmd's quoting rules (pipes, braces, quotes) is a reliable source of
# silent breakage.
#
# Matches on command lines, not window titles - see the comment in stop.bat.

$ErrorActionPreference = 'SilentlyContinue'

$patterns = @(
    'uvicorn\s+grimoire\.main:app',
    'grimoire\.worker\.run',
    'grimoire\.worker\.tasks\.huey',
    'grimoire[\\/]frontend.*vite'
)

$all = Get-CimInstance Win32_Process
$hits = $all | Where-Object {
    $cmdline = $_.CommandLine
    $cmdline -and ($patterns | Where-Object { $cmdline -match $_ })
}

if (-not $hits) {
    Write-Host '  Nothing running.'
    exit 0
}

# Collect the matched processes plus their cmd.exe wrappers. Each service runs
# as `cmd /c "... python -m ..."`, so killing only the python/node process
# leaves the wrapper behind. Walk up at most 3 hops and stop at the first
# non-cmd.exe parent, so this can never climb out into the shell that invoked
# the script.
$targets = New-Object System.Collections.Generic.HashSet[int]
foreach ($proc in $hits) {
    [void]$targets.Add([int]$proc.ProcessId)
    $current = $proc
    for ($hop = 0; $hop -lt 3; $hop++) {
        $parent = $all | Where-Object { $_.ProcessId -eq $current.ParentProcessId }
        if (-not $parent -or $parent.Name -ne 'cmd.exe') { break }
        [void]$targets.Add([int]$parent.ProcessId)
        $current = $parent
    }
}

foreach ($processId in $targets) {
    $name = ($all | Where-Object { $_.ProcessId -eq $processId }).Name
    Write-Host ('  stopping PID ' + $processId + ' (' + $name + ')')
    $null = & taskkill /PID $processId /T /F 2>&1
}

Start-Sleep -Milliseconds 800

$survivors = @(Get-CimInstance Win32_Process | Where-Object {
    $cmdline = $_.CommandLine
    $cmdline -and ($patterns | Where-Object { $cmdline -match $_ })
})

if ($survivors.Count -gt 0) {
    Write-Host ('  WARNING: ' + $survivors.Count + ' process(es) still alive')
    exit 1
}

Write-Host '  All services stopped.'
exit 0
