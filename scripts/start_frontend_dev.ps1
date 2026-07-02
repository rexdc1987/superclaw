param(
  [int]$Port = 3000
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("vite-dev-{0}.log" -f (Get-Date -Format "yyyyMMdd"))

function Write-DevLog($message) {
  $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message
  $line | Tee-Object -FilePath $logFile -Append
}

Write-DevLog "Starting Vite dev server on port $Port"
Write-DevLog "Repo root: $repoRoot"
Write-DevLog "Frontend root: $frontendRoot"

Set-Location $frontendRoot
$env:PORT = [string]$Port

try {
  & npm run dev -- --port $Port 2>&1 | ForEach-Object {
    "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $_
  } | Tee-Object -FilePath $logFile -Append
} catch {
  Write-DevLog ("Vite dev server failed: " + $_.Exception.Message)
  throw
} finally {
  Write-DevLog "Vite dev server stopped"
}
