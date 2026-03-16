param(
    [string]$RepoRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$runtimeDir = Join-Path $RepoRoot ".runtime"
$statePath = Join-Path $runtimeDir "local_stack_state.json"

if (-not (Test-Path $statePath)) {
    Write-Host "No state file found: $statePath"
    exit 0
}

$state = Get-Content -Path $statePath -Raw | ConvertFrom-Json
Write-Host ("started_at: " + $state.started_at)
Write-Host ("mysql: " + $state.mysql_user + "@" + $state.mysql_host + ":" + $state.mysql_port + "/" + $state.mysql_db)

foreach ($key in @("bridge_codex_pid", "bridge_claude_pid", "bridge_gemini_pid", "dispatcher_pid")) {
    if ($state.PSObject.Properties.Name -contains $key) {
        $pidValue = [int]$state.$key
        if ($pidValue -le 0) { continue }
        $p = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($null -eq $p) {
            Write-Host ("[dead] " + $key + "=" + $pidValue)
        } else {
            Write-Host ("[alive] " + $key + "=" + $pidValue + " (" + $p.ProcessName + ")")
        }
    }
}

if (Test-Path $runtimeDir) {
    Write-Host ("logs: " + $runtimeDir)
}

foreach ($key in @("bridge_codex_out_log","bridge_codex_err_log","dispatcher_out_log","dispatcher_err_log","bridge_claude_out_log","bridge_claude_err_log","bridge_gemini_out_log","bridge_gemini_err_log")) {
    if ($state.PSObject.Properties.Name -contains $key) {
        Write-Host ($key + ": " + [string]$state.$key)
    }
}
