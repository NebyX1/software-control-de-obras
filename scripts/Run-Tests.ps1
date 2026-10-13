param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$exit = 0

if (-not $SkipBackend) {
    Push-Location (Join-Path $root 'backend')
    & '.\.venv\Scripts\python.exe' -m pytest -q
    if ($LASTEXITCODE -ne 0) { $exit = $LASTEXITCODE; Write-Output 'Backend: FALLÓ' } else { Write-Output 'Backend: OK' }
    Pop-Location
}

if (-not $SkipFrontend) {
    Push-Location (Join-Path $root 'frontend')
    npm run build
    if ($LASTEXITCODE -ne 0) { $exit = $LASTEXITCODE; Write-Output 'Frontend: FALLÓ' } else { Write-Output 'Frontend: OK' }
    Pop-Location
}

exit $exit
