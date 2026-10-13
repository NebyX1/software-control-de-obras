param(
    [switch]$WithMail
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path '.env')) {
    Write-Error 'Falta .env. Ejecutá scripts\Initialize-Environment.ps1 primero.'
    exit 1
}

$files = @('-f', 'docker-compose.yml', '-f', 'docker-compose.local.yml')
$profile = @()
if ($WithMail) { $profile = @('--profile', 'local') }

docker compose @files @profile up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose up falló (código $LASTEXITCODE)."
    exit $LASTEXITCODE
}

Write-Output 'Stack levantado. Verificá con scripts\Test-Stack.ps1.'
Write-Output 'Aplicación: http://127.0.0.1:8080'
