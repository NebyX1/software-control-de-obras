#Requires -Version 5.1
<#
.SYNOPSIS
  Crea el archivo .env privado de Compra Clara con secretos generados localmente.

.DESCRIPTION
  - Genera SECRET_KEY y contraseñas de MariaDB aleatorias (solo hexadecimal, sin codificación de URL).
  - No sobrescribe un .env existente salvo con -Force.
  - Toma únicamente el nombre del modelo de Ollama de sample/backend/.env. No copia su clave:
    el marcador de ese archivo corresponde a un Ollama local, no a Ollama Cloud.
  - Nunca imprime valores secretos; solo nombres de variables.
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [string]$PublicOrigin = 'http://localhost:8080',
    [int]$LocalHttpPort = 8080
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root '.env'
$sampleEnv = Join-Path $root 'sample\backend\.env'

if ((Test-Path $target) -and -not $Force) {
    Write-Host '.env ya existe; no se modifica. Usá -Force para regenerarlo (los secretos anteriores se perderán).'
    exit 0
}

function New-HexSecret([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return -join ($buffer | ForEach-Object { $_.ToString('x2') })
}

$ollamaModel = ''
if (Test-Path $sampleEnv) {
    $line = Get-Content $sampleEnv | Where-Object { $_ -match '^\s*OLLAMA_MODEL\s*=' } | Select-Object -First 1
    if ($line) { $ollamaModel = $line.Split('=', 2)[1].Trim().Trim('"', "'") }
}

$lines = @(
    '# Archivo privado generado por scripts/Initialize-Environment.ps1. No versionar.',
    '',
    '# Secretos generados localmente',
    "SECRET_KEY=$(New-HexSecret 32)",
    "MARIADB_ROOT_PASSWORD=$(New-HexSecret 24)",
    "MARIADB_PASSWORD=$(New-HexSecret 24)",
    'MARIADB_DATABASE=compra_clara',
    'MARIADB_USER=compra_clara',
    '',
    '# Origen público y red',
    "PUBLIC_ORIGIN=$PublicOrigin",
    "LOCAL_HTTP_PORT=$LocalHttpPort",
    'TRUST_PROXY=1',
    'COOKIE_SECURE=false',
    '',
    '# Demostración: las semillas demo solo se cargan con este flag explícito',
    'ALLOW_DEMO_SEED=false',
    '',
    '# IA: Ollama Cloud. La clave se completa manualmente; no se copia de ningún archivo de referencia.',
    'AI_ENABLED=false',
    'OLLAMA_HOST=https://ollama.com',
    "OLLAMA_MODEL=$ollamaModel",
    'OLLAMA_API_KEY=',
    '',
    '# Correo: en el perfil local se usa Mailpit (docker compose --profile local)',
    'MAIL_SERVER=mailpit',
    'MAIL_PORT=1025',
    'MAIL_USE_TLS=false',
    'MAIL_DEFAULT_SENDER=no-reply@compra-clara.local'
)

[System.IO.File]::WriteAllText($target, (($lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding($false)))

$names = $lines | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object { $_.Split('=', 2)[0] }
Write-Host ".env creado con $($names.Count) variables. Claves presentes: $($names -join ', ')"
if (-not $ollamaModel) { Write-Host 'Aviso: OLLAMA_MODEL quedó vacío; configurarlo antes de habilitar la IA.' }
Write-Host 'Aviso: OLLAMA_API_KEY vacía. La IA permanece deshabilitada hasta completarla y poner AI_ENABLED=true.'
