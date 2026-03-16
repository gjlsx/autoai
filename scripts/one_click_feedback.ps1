param(
    [Parameter(Mandatory = $true)]
    [string]$TaskId,
    [Parameter(Mandatory = $true)]
    [string]$Message,
    [string]$SourceAI = "codex",
    [string]$RepoRoot = "",
    [string]$PythonExe = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$envPath = Join-Path $RepoRoot ".env"
if (-not (Test-Path $envPath)) {
    throw ".env not found: $envPath"
}

$text = Get-Content -Path $envPath -Raw
$hostMatch = [regex]::Match($text, "(?m)^\s*([A-Za-z0-9\.-]+)[ \t]+(\d{2,5})\s*$")
$credMatch = [regex]::Match($text, "(?mi)^\s*([A-Za-z0-9_]+)[ \t]+[^\r\n]*?pwd:\s*([^\s]+)\s*$")
if (-not $hostMatch.Success -or -not $credMatch.Success) {
    throw "cannot parse mysql config from .env"
}

$mysqlHost = $hostMatch.Groups[1].Value
$mysqlPort = $hostMatch.Groups[2].Value
$mysqlUser = $credMatch.Groups[1].Value
$mysqlPassword = $credMatch.Groups[2].Value
$dbMatch = [regex]::Match($mysqlUser, "^(.*)wr$")
$mysqlDb = if ($dbMatch.Success) { $dbMatch.Groups[1].Value } else { "autoai" }

$old = @{
    MYSQL_HOST = [Environment]::GetEnvironmentVariable("MYSQL_HOST", "Process")
    MYSQL_PORT = [Environment]::GetEnvironmentVariable("MYSQL_PORT", "Process")
    MYSQL_USER = [Environment]::GetEnvironmentVariable("MYSQL_USER", "Process")
    MYSQL_PASSWORD = [Environment]::GetEnvironmentVariable("MYSQL_PASSWORD", "Process")
    MYSQL_DB = [Environment]::GetEnvironmentVariable("MYSQL_DB", "Process")
}

[Environment]::SetEnvironmentVariable("MYSQL_HOST", $mysqlHost, "Process")
[Environment]::SetEnvironmentVariable("MYSQL_PORT", $mysqlPort, "Process")
[Environment]::SetEnvironmentVariable("MYSQL_USER", $mysqlUser, "Process")
[Environment]::SetEnvironmentVariable("MYSQL_PASSWORD", $mysqlPassword, "Process")
[Environment]::SetEnvironmentVariable("MYSQL_DB", $mysqlDb, "Process")

try {
    & $PythonExe "ai_feedback.py" "--source-ai" $SourceAI "--task-id" $TaskId "--db" $Message
} finally {
    foreach ($k in $old.Keys) {
        [Environment]::SetEnvironmentVariable($k, $old[$k], "Process")
    }
}

