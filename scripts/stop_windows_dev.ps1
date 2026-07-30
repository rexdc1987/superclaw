[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$RunDir = Join-Path $ProjectRoot '.run'

foreach ($name in @('api', 'frontend')) {
    $pidFile = Join-Path $RunDir "$name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $processId = [int](Get-Content -LiteralPath $pidFile -Raw)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $processId -Force
        Write-Host "Stopped $name process $processId"
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
