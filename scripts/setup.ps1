$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    & python @('-m', 'venv', '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
}
& $pythonExe @('-m', 'pip', 'install', '-r', 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $pythonExe @('-m', 'pip', 'install', '-e', '.', '--no-deps')
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    Write-Host 'Fill DEEPSEEK_API_KEY in .env before starting a model run.'
}
Write-Host 'Ready. Run pwsh -File scripts/start.ps1'

