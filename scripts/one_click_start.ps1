param(
    [string]$RepoRoot = "",
    [string]$PythonExe = "python",
    [string]$Routing = "claude=9001,gemini=9002,codex=9003",
    [switch]$StartClaude,
    [switch]$StartGemini,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$runtimeDir = Join-Path $RepoRoot ".runtime"
$statePath = Join-Path $runtimeDir "local_stack_state.json"
$envPath = Join-Path $RepoRoot ".env"
$runId = (Get-Date).ToString("yyyyMMdd-HHmmss")
$requiredPorts = @(9003)
if ($StartClaude) { $requiredPorts += 9001 }
if ($StartGemini) { $requiredPorts += 9002 }

function Get-StandardEnvValue {
    param(
        [string]$Text,
        [string]$Name
    )
    $m = [regex]::Match($Text, "(?m)^\s*" + [regex]::Escape($Name) + "\s*=\s*(.+?)\s*$")
    if ($m.Success) {
        $v = $m.Groups[1].Value.Trim()
        return $v.Trim("'`"")
    }
    return $null
}

function Parse-ProjectEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw ".env not found: $Path"
    }

    $text = Get-Content -Path $Path -Raw
    $mysqlHost = Get-StandardEnvValue -Text $text -Name "MYSQL_HOST"
    $mysqlPort = Get-StandardEnvValue -Text $text -Name "MYSQL_PORT"
    $mysqlUser = Get-StandardEnvValue -Text $text -Name "MYSQL_USER"
    $mysqlPassword = Get-StandardEnvValue -Text $text -Name "MYSQL_PASSWORD"
    $mysqlDb = Get-StandardEnvValue -Text $text -Name "MYSQL_DB"

    if (-not $mysqlHost -or -not $mysqlPort) {
        $mHost = [regex]::Match($text, "(?m)^\s*([A-Za-z0-9\.-]+)[ \t]+(\d{2,5})\s*$")
        if ($mHost.Success) {
            if (-not $mysqlHost) { $mysqlHost = $mHost.Groups[1].Value }
            if (-not $mysqlPort) { $mysqlPort = $mHost.Groups[2].Value }
        }
    }

    if (-not $mysqlUser -or -not $mysqlPassword) {
        $mUser = [regex]::Match($text, "(?mi)^\s*([A-Za-z0-9_]+)[ \t]+[^\r\n]*?pwd:\s*([^\s]+)\s*$")
        if ($mUser.Success) {
            if (-not $mysqlUser) { $mysqlUser = $mUser.Groups[1].Value }
            if (-not $mysqlPassword) { $mysqlPassword = $mUser.Groups[2].Value }
        }
    }

    if (-not $mysqlUser -or -not $mysqlPassword) {
        foreach ($line in (Get-Content -Path $Path)) {
            if ($line -match "(?i)^\s*([A-Za-z0-9_]+)[ \t]+[^\r\n]*?pwd:\s*([^\s]+)\s*$") {
                if (-not $mysqlUser) { $mysqlUser = $Matches[1] }
                if (-not $mysqlPassword) { $mysqlPassword = $Matches[2] }
                break
            }
        }
    }

    if (-not $mysqlDb -and $mysqlUser) {
        # Heuristic for current legacy env: edcarwr -> edcar.
        $mDb = [regex]::Match($mysqlUser, "^(.*)wr$")
        if ($mDb.Success -and $mDb.Groups[1].Value) {
            $mysqlDb = $mDb.Groups[1].Value
        }
    }

    if (-not $mysqlHost -or -not $mysqlPort -or -not $mysqlUser -or -not $mysqlPassword -or -not $mysqlDb) {
        throw "cannot parse mysql config from .env, please provide MYSQL_HOST/MYSQL_PORT/MYSQL_USER/MYSQL_PASSWORD/MYSQL_DB"
    }
    return [pscustomobject]@{
        mysql_host = $mysqlHost
        mysql_port = $mysqlPort
        mysql_user = $mysqlUser
        mysql_password = $mysqlPassword
        mysql_db = $mysqlDb
    }
}

function Stop-OldProcesses {
    param([string]$StateFile)
    if (-not (Test-Path $StateFile)) { return }
    try {
        $state = Get-Content -Path $StateFile -Raw | ConvertFrom-Json
    } catch {
        return
    }
    foreach ($key in @("bridge_codex_pid", "bridge_claude_pid", "bridge_gemini_pid", "dispatcher_pid")) {
        if ($state.PSObject.Properties.Name -contains $key) {
            $pidValue = [int]$state.$key
            if ($pidValue -gt 0) {
                Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Stop-ManagedPythonByCommandLine {
    param([string]$Repo)
    $patterns = @("window_bridge.py", "dispatcher.py")
    $procList = Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procList) {
        $cmd = [string]$p.CommandLine
        if (-not $cmd) { continue }
        if ($cmd -notlike "*$Repo*") { continue }
        foreach ($pattern in $patterns) {
            if ($cmd -like "*$pattern*") {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                break
            }
        }
    }
}

function Stop-PythonByPort {
    param([int[]]$Ports)
    foreach ($port in $Ports) {
        try {
            $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
        } catch {
            continue
        }
        foreach ($listener in $listeners) {
            $pidValue = [int]$listener.OwningProcess
            $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
            if ($null -ne $proc -and $proc.ProcessName -eq "python") {
                Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Assert-ProcessAlive {
    param(
        [string]$Name,
        [int]$ProcId,
        [string]$OutPath,
        [string]$ErrPath
    )
    Start-Sleep -Milliseconds 400
    $p = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
    if ($null -ne $p) { return }

    $err = $ErrPath
    $out = $OutPath
    $errText = ""
    $outText = ""
    if (Test-Path $err) {
        $errText = (Get-Content -Path $err -ErrorAction SilentlyContinue | Select-Object -First 20) -join [Environment]::NewLine
    }
    if (Test-Path $out) {
        $outText = (Get-Content -Path $out -ErrorAction SilentlyContinue | Select-Object -First 20) -join [Environment]::NewLine
    }
    throw "process '$Name' pid=$ProcId exited early. err=`n$errText`nout=`n$outText"
}

function Assert-BridgePortListening {
    param(
        [string]$Name,
        [int]$Port,
        [string]$ErrPath
    )
    Start-Sleep -Milliseconds 500
    try {
        $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
    } catch {
        $listeners = @()
    }
    if (@($listeners).Count -gt 0) { return }
    $err = $ErrPath
    $errText = ""
    if (Test-Path $err) {
        $errText = (Get-Content -Path $err -ErrorAction SilentlyContinue | Select-Object -First 30) -join [Environment]::NewLine
    }
    throw "bridge '$Name' not listening on port $Port. err=`n$errText"
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string[]]$ProcArgs,
        [hashtable]$Environment = @{}
    )
    $out = Join-Path $runtimeDir ($Name + "." + $runId + ".out.log")
    $err = Join-Path $runtimeDir ($Name + "." + $runId + ".err.log")

    if ($DryRun) {
        Write-Host "[dryrun] $PythonExe $($ProcArgs -join ' ')"
        if ($Environment.Count -gt 0) {
            Write-Host "[dryrun] env keys: $($Environment.Keys -join ', ')"
        }
        return @{ Id = 0; Out = $out; Err = $err }
    }

    $startProcessHasEnvironment = (Get-Command Start-Process).Parameters.ContainsKey("Environment")

    if ($Environment.Count -gt 0 -and $startProcessHasEnvironment) {
        $p = Start-Process -FilePath $PythonExe `
            -ArgumentList $ProcArgs `
            -WorkingDirectory $RepoRoot `
            -RedirectStandardOutput $out `
            -RedirectStandardError $err `
            -Environment $Environment `
            -PassThru
        return @{ Id = $p.Id; Out = $out; Err = $err }
    }

    $oldEnv = @{}
    foreach ($k in $Environment.Keys) {
        $oldEnv[$k] = [Environment]::GetEnvironmentVariable($k, "Process")
        [Environment]::SetEnvironmentVariable($k, [string]$Environment[$k], "Process")
    }
    try {
        $p = Start-Process -FilePath $PythonExe `
            -ArgumentList $ProcArgs `
            -WorkingDirectory $RepoRoot `
            -RedirectStandardOutput $out `
            -RedirectStandardError $err `
            -PassThru
    } finally {
        foreach ($k in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($k, $oldEnv[$k], "Process")
        }
    }
    return @{ Id = $p.Id; Out = $out; Err = $err }
}

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
Stop-OldProcesses -StateFile $statePath
Stop-ManagedPythonByCommandLine -Repo $RepoRoot
Stop-PythonByPort -Ports $requiredPorts

$cfg = Parse-ProjectEnv -Path $envPath
if ($DryRun) {
    Write-Host ("[dryrun] mysql=" + $cfg.mysql_user + "@" + $cfg.mysql_host + ":" + $cfg.mysql_port + "/" + $cfg.mysql_db)
}

$state = [ordered]@{
    started_at = (Get-Date).ToString("s")
    run_id = $runId
    mysql_host = $cfg.mysql_host
    mysql_port = [int]$cfg.mysql_port
    mysql_user = $cfg.mysql_user
    mysql_db = $cfg.mysql_db
}

$bridgeCodex = Start-ManagedProcess -Name "bridge_codex" -ProcArgs @(
    "-u",
    "window_bridge.py",
    "--ai", "codex",
    "--port", "9003",
    "--cli", "codex"
)
$state.bridge_codex_pid = $bridgeCodex.Id
$state.bridge_codex_out_log = $bridgeCodex.Out
$state.bridge_codex_err_log = $bridgeCodex.Err
if (-not $DryRun) {
    Assert-ProcessAlive -Name "bridge_codex" -Pid $bridgeCodex.Id -OutPath $bridgeCodex.Out -ErrPath $bridgeCodex.Err
    Assert-BridgePortListening -Name "bridge_codex" -Port 9003 -ErrPath $bridgeCodex.Err
}

if ($StartClaude) {
    $bridgeClaude = Start-ManagedProcess -Name "bridge_claude" -ProcArgs @(
        "-u",
        "window_bridge.py",
        "--ai", "claude",
        "--port", "9001",
        "--cli", "claude"
    )
    $state.bridge_claude_pid = $bridgeClaude.Id
    $state.bridge_claude_out_log = $bridgeClaude.Out
    $state.bridge_claude_err_log = $bridgeClaude.Err
    if (-not $DryRun) {
        Assert-ProcessAlive -Name "bridge_claude" -Pid $bridgeClaude.Id -OutPath $bridgeClaude.Out -ErrPath $bridgeClaude.Err
        Assert-BridgePortListening -Name "bridge_claude" -Port 9001 -ErrPath $bridgeClaude.Err
    }
}

if ($StartGemini) {
    $bridgeGemini = Start-ManagedProcess -Name "bridge_gemini" -ProcArgs @(
        "-u",
        "window_bridge.py",
        "--ai", "gemini",
        "--port", "9002",
        "--cli", "gemini"
    )
    $state.bridge_gemini_pid = $bridgeGemini.Id
    $state.bridge_gemini_out_log = $bridgeGemini.Out
    $state.bridge_gemini_err_log = $bridgeGemini.Err
    if (-not $DryRun) {
        Assert-ProcessAlive -Name "bridge_gemini" -Pid $bridgeGemini.Id -OutPath $bridgeGemini.Out -ErrPath $bridgeGemini.Err
        Assert-BridgePortListening -Name "bridge_gemini" -Port 9002 -ErrPath $bridgeGemini.Err
    }
}

$dispatcherEnv = @{
    MYSQL_HOST = $cfg.mysql_host
    MYSQL_PORT = [string]$cfg.mysql_port
    MYSQL_USER = $cfg.mysql_user
    MYSQL_PASSWORD = $cfg.mysql_password
    MYSQL_DB = $cfg.mysql_db
}

$dispatcher = Start-ManagedProcess -Name "dispatcher" -ProcArgs @(
    "-u",
    "dispatcher.py",
    "--disable-redis",
    "--enable-mysql",
    "--no-user-input",
    "--routing", $Routing
) -Environment $dispatcherEnv
$state.dispatcher_pid = $dispatcher.Id
$state.dispatcher_out_log = $dispatcher.Out
$state.dispatcher_err_log = $dispatcher.Err
if (-not $DryRun) {
    Assert-ProcessAlive -Name "dispatcher" -Pid $dispatcher.Id -OutPath $dispatcher.Out -ErrPath $dispatcher.Err
}

$state | ConvertTo-Json -Depth 4 | Set-Content -Path $statePath -Encoding UTF8

Write-Host "AutoAI local stack started."
Write-Host "State file: $statePath"
Write-Host "Logs: $runtimeDir"
Write-Host "Tip: use scripts/one_click_stop.ps1 to stop all."
