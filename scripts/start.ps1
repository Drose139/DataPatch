param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Run scripts/setup.ps1 first to create the Python environment.'
}
$env:PYTHONUTF8 = '1'
Write-Host "DataPatch: http://127.0.0.1:$Port"
$nativeArgs = @('-m', 'datapatch.cli', 'serve', '--host', '127.0.0.1', '--port', [string]$Port)
& $pythonExe @nativeArgs
if ($LASTEXITCODE -ne 0) { throw 'DataPatch server stopped with an error.' }

