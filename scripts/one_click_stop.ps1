param(
    [string]$RepoRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$statePath = Join-Path (Join-Path $RepoRoot ".runtime") "local_stack_state.json"
$runtimeDir = Join-Path $RepoRoot ".runtime"
$killed = @()

if (Test-Path $statePath) {
    $state = Get-Content -Path $statePath -Raw | ConvertFrom-Json
    foreach ($key in @("bridge_codex_pid", "bridge_claude_pid", "bridge_gemini_pid", "dispatcher_pid")) {
        if ($state.PSObject.Properties.Name -contains $key) {
            $pidValue = [int]$state.$key
            if ($pidValue -gt 0) {
                try {
                    Stop-Process -Id $pidValue -Force -ErrorAction Stop
                    $killed += "$key=$pidValue"
                } catch {
                    # ignore already-exited processes
                }
            }
        }
    }
}

# fallback cleanup by command line
$procList = Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue
foreach ($p in $procList) {
    $cmd = [string]$p.CommandLine
    if (-not $cmd) { continue }
    if ($cmd -notlike "*$RepoRoot*") { continue }
    if ($cmd -like "*window_bridge.py*" -or $cmd -like "*dispatcher.py*") {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            $killed += "proc=$($p.ProcessId)"
        } catch {
        }
    }
}

# fallback cleanup by required local ports
foreach ($port in @(9001,9002,9003)) {
    try {
        $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
    } catch {
        $listeners = @()
    }
    foreach ($listener in $listeners) {
        $pidValue = [int]$listener.OwningProcess
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($null -ne $proc -and $proc.ProcessName -eq "python") {
            try {
                Stop-Process -Id $pidValue -Force -ErrorAction Stop
                $killed += "port${port}_pid=$pidValue"
            } catch {
            }
        }
    }
}

Write-Host "Stopped: $($killed -join ', ')"
if (Test-Path $runtimeDir) {
    Get-ChildItem -Path $runtimeDir -File -ErrorAction SilentlyContinue | Out-Null
}
